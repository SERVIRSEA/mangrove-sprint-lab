"""MCP adapter over the platform's remote streamable-HTTP endpoint, using the official SDK.

GRP talks to `https://servirplatform.sig-gis.com/mcp` the same way: streamable HTTP with the
person's bearer token. stdio is not offered because no server command is known for the hosted
platform. The SDK owns the protocol; this module only adds the token, discovery, schema checks
and the common result shape.

Tool arguments are checked against the schema the server advertised in this session before a call.
A tool name is never turned into a REST URL.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mangrove_sprint_lab.config import Environment
from mangrove_sprint_lab.platform.results import OperationResult
from mangrove_sprint_lab.platform.token_provider import SignInRequired, TokenProvider
from mangrove_sprint_lab.redact import redact, redact_text
from mangrove_sprint_lab.traces import Trace

CLIENT_NAME = "mangrove-sprint-lab"
# Tools this lab may call without an explicit write confirmation. Everything else that is not
# contribute_submit is refused until someone reviews it and adds it here.
READ_ONLY_TOOLS = {"platform_capabilities", "contribute_status", "feeds_query"}
WRITE_TOOLS = {"contribute_submit"}

SessionFactory = Callable[[str, dict[str, str], float], Any]


def _auth_failure(error: BaseException) -> bool:
    """True when the SDK surfaced an HTTP 401/403 somewhere in an exception group."""

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {401, 403}
    for inner in getattr(error, "exceptions", ()) or ():
        if _auth_failure(inner):
            return True
    cause = error.__cause__ or error.__context__
    return cause is not None and cause is not error and _auth_failure(cause)


def _first_error(error: BaseException) -> BaseException:
    inner = getattr(error, "exceptions", None)
    return _first_error(inner[0]) if inner else error


@asynccontextmanager
async def http_session(url: str, headers: dict[str, str], timeout: float):
    """A real SDK session over streamable HTTP. Replaced by a fake in tests."""

    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(timeout, read=max(timeout, 300.0))
    ) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json", by_alias=True, exclude_none=True) if hasattr(
        value, "model_dump"
    ) else value


class McpPlatformClient:
    adapter = "mcp"

    def __init__(
        self,
        environment: Environment,
        tokens: TokenProvider,
        *,
        session_factory: SessionFactory = http_session,
    ) -> None:
        self.environment = environment
        self.tokens = tokens
        self._session_factory = session_factory
        self.tools: dict[str, dict[str, Any]] = {}
        # Set once a write tool's request has been handed to the SDK: from then on a failure
        # means the platform may already hold the contribution.
        self._write_dispatched = False

    def _result(self, operation: str, state: str, **values: Any) -> OperationResult:
        return OperationResult(
            state=state,
            operation=operation,
            adapter=self.adapter,
            environment=self.environment.name,
            **values,
        )

    async def _run(
        self,
        operation: str,
        trace: Trace,
        body: Callable[[Any], Awaitable[OperationResult]],
    ) -> OperationResult:
        try:
            token = self.tokens.access_token()
        except SignInRequired as error:
            return self._result(operation, "sign_in_required", error=str(error))
        headers = {"Authorization": f"Bearer {token}"}
        url = self.environment.mcp_url
        self._write_dispatched = False
        try:
            async with self._session_factory(url, headers, self.environment.request_timeout) as s:
                result = await body(s)
        except Exception as error:  # noqa: BLE001 - the SDK raises exception groups
            trace.call(transport="streamable-http", url=url, error=type(error).__name__)
            if _auth_failure(error):
                return self._result(
                    operation,
                    "sign_in_required",
                    http_status=401,
                    error="The MCP endpoint did not accept the token. Refresh it with "
                    "`python tools/grp-login.py token`, or sign in again.",
                )
            first = _first_error(error)
            detail = redact_text(f"{type(first).__name__}: {first}", self.tokens.secrets())
            if self._write_dispatched:
                return self._result(
                    operation,
                    "outcome_unknown",
                    error=f"The submit was sent but no answer arrived ({detail[:200]}). The "
                    "platform may already hold it. Do NOT resend; check `contribute_status {}`.",
                )
            return self._result(operation, "failed", error=f"MCP call failed ({detail[:300]}).")
        trace.call(transport="streamable-http", url=url, operation=operation, state=result.state)
        return result

    async def _refresh_tools(self, session: Any) -> None:
        listed = await session.list_tools()
        self.tools = {
            tool.name: {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in listed.tools
        }

    async def discover(self, trace: Trace) -> OperationResult:
        """Refresh the tool list and schemas; also list resources when offered."""

        async def body(session: Any) -> OperationResult:
            await self._refresh_tools(session)
            resources: list[Any] | str
            try:
                listed = await session.list_resources()
                resources = [_dump(item) for item in listed.resources]
            except Exception as error:  # noqa: BLE001
                resources = f"not listed ({type(error).__name__})"
            return self._result(
                "discover",
                "ok",
                data={"tools": list(self.tools.values()), "resources": resources},
            )

        return await self._run("discover", trace, body)

    def check_arguments(self, name: str, arguments: dict[str, Any]) -> str | None:
        """Problem text when `arguments` do not satisfy the discovered schema, else None."""

        tool = self.tools.get(name)
        if tool is None:
            return f"The server did not advertise {name!r} in this session; run discover first."
        try:
            jsonschema.validate(arguments, tool.get("inputSchema") or {"type": "object"})
        except jsonschema.ValidationError as error:
            return f"Arguments do not match the advertised schema: {error.message}"
        except jsonschema.SchemaError:
            return None  # A schema the validator cannot read is the server's to enforce.
        return None

    async def call_tool(
        self, name: str, arguments: dict[str, Any], trace: Trace, *, allow_write: bool = False
    ) -> OperationResult:
        if name in WRITE_TOOLS and not allow_write:
            return self._result(
                name, "failed", error=f"{name} writes to the platform; use the submit command."
            )
        if name not in READ_ONLY_TOOLS | WRITE_TOOLS:
            return self._result(
                name,
                "unsupported",
                error=f"{name} is not on this lab's reviewed tool list (READ_ONLY_TOOLS).",
            )

        async def body(session: Any) -> OperationResult:
            await self._refresh_tools(session)
            problem = self.check_arguments(name, arguments)
            if problem:
                return self._result(name, "failed", error=problem)
            self._write_dispatched = name in WRITE_TOOLS
            called = await session.call_tool(name, arguments)
            structured = called.structuredContent
            content = [_dump(item) for item in called.content]
            data = structured if structured is not None else _text_payload(content)
            if isinstance(data, dict):
                trace.platform_trace = data.get("trace")
            secrets = self.tokens.secrets()
            if called.isError:
                return self._result(
                    name, "failed", error="The tool reported an error.",
                    data=redact(data, secrets), raw=redact(content, secrets),
                )
            return self._result(
                name, "ok", data=redact(data, secrets), raw=redact(content, secrets)
            )

        return await self._run(name, trace, body)

    async def read_resource(self, uri: str, trace: Trace) -> OperationResult:
        async def body(session: Any) -> OperationResult:
            read = await session.read_resource(uri)
            contents = [_dump(item) for item in read.contents]
            return self._result("read_resource", "ok", data=redact(contents))

        return await self._run("read_resource", trace, body)

    async def probe_unauthenticated(self, trace: Trace) -> OperationResult:
        """Live check with no token: a 401 + WWW-Authenticate proves the endpoint and the
        sign-in path, nothing more. Uses plain HTTP, not a session, because none can open."""

        url = self.environment.mcp_url
        async with httpx.AsyncClient(timeout=self.environment.request_timeout) as http:
            try:
                response = await http.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    headers={"Accept": "application/json, text/event-stream"},
                )
            except httpx.HTTPError as error:
                trace.call(method="POST", url=url, error=type(error).__name__)
                return self._result("probe", "failed", error=type(error).__name__)
        trace.call(method="POST", url=url, status=response.status_code)
        state = "sign_in_required" if response.status_code == 401 else "failed"
        return self._result(
            "probe",
            state,
            http_status=response.status_code,
            raw={"www_authenticate": response.headers.get("www-authenticate")},
        )


def _text_payload(content: list[dict[str, Any]]) -> Any:
    """Unstructured tool output: parse a single JSON text block, else keep the blocks."""

    texts = [item.get("text") for item in content if item.get("type") == "text"]
    if len(texts) == 1 and isinstance(texts[0], str):
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return {"text": texts[0]}
    return {"content": content}

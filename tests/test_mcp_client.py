from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx

from conftest import FAKE_TOKEN, FakeTokens
from mangrove_sprint_lab.platform.mcp_client import McpPlatformClient
from mangrove_sprint_lab.traces import TraceLog

SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string"}, "manifest": {"type": "object"}},
    "required": ["kind", "manifest"],
}
STATUS_SCHEMA = {"type": "object", "properties": {"contribution_id": {"type": "string"}}}


class FakeSession:
    def __init__(self, *, call_result=None, call_error: BaseException | None = None) -> None:
        self.call_result = call_result
        self.call_error = call_error
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        tools = [
            SimpleNamespace(name="contribute_submit", description="d", inputSchema=SUBMIT_SCHEMA),
            SimpleNamespace(name="contribute_status", description="d", inputSchema=STATUS_SCHEMA),
            SimpleNamespace(name="platform_capabilities", description="d", inputSchema={}),
        ]
        return SimpleNamespace(tools=tools)

    async def list_resources(self):
        return SimpleNamespace(resources=[{"uri": "servirplatform://skill/trace-emit"}])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.call_error:
            raise self.call_error
        return self.call_result


def _factory(session: FakeSession, seen: dict | None = None, open_error=None):
    @asynccontextmanager
    async def factory(url, headers, timeout):
        if seen is not None:
            seen.update(url=url, headers=headers)
        if open_error:
            raise open_error
        yield session

    return factory


def _client(environment, session, **kwargs):
    env = environment("mcp")
    client = McpPlatformClient(
        env, kwargs.pop("tokens", FakeTokens()), session_factory=_factory(session, **kwargs)
    )
    return client, TraceLog(env.outputs_dir)


def _run(log, coroutine_factory):
    with log.trace("op", "mcp", "test") as trace:
        return asyncio.run(coroutine_factory(trace))


def test_discover_lists_tools_and_sends_bearer_to_mcp_url(environment):
    seen: dict = {}
    client, log = _client(environment, FakeSession(), seen=seen)
    result = _run(log, client.discover)
    assert result.ok
    assert {tool["name"] for tool in result.data["tools"]} >= {"contribute_submit"}
    assert seen["url"] == "https://servirplatform.sig-gis.com/mcp"
    assert seen["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_arguments_are_checked_against_the_advertised_schema(environment):
    session = FakeSession()
    client, log = _client(environment, session)
    result = _run(
        log,
        lambda t: client.call_tool("contribute_submit", {"kind": "vector"}, t, allow_write=True),
    )
    assert result.state == "failed"
    assert "advertised schema" in result.error
    assert session.calls == []


def test_unreviewed_tool_is_unsupported(environment):
    client, log = _client(environment, FakeSession())
    result = _run(log, lambda t: client.call_tool("compose_run", {}, t))
    assert result.state == "unsupported"


def test_write_tool_needs_the_submit_path(environment):
    session = FakeSession()
    client, log = _client(environment, session)
    result = _run(log, lambda t: client.call_tool("contribute_submit", {}, t))
    assert result.state == "failed"
    assert session.calls == []


def test_structured_result_is_returned_verbatim(environment):
    called = SimpleNamespace(
        structuredContent={"status": "staged", "contribution_id": "c1"}, content=[], isError=False
    )
    client, log = _client(environment, FakeSession(call_result=called))
    result = _run(
        log,
        lambda t: client.call_tool(
            "contribute_submit", {"kind": "vector", "manifest": {}}, t, allow_write=True
        ),
    )
    assert result.ok and result.contribution_status() == "staged"


def test_text_json_result_is_parsed(environment):
    called = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(model_dump=lambda **_: {"type": "text", "text": '{"a": 1}'})],
        isError=False,
    )
    client, log = _client(environment, FakeSession(call_result=called))
    result = _run(log, lambda t: client.call_tool("contribute_status", {}, t))
    assert result.data == {"a": 1}


def test_http_401_inside_exception_group_is_sign_in_required(environment):
    request = httpx.Request("POST", "https://servirplatform.sig-gis.com/mcp")
    error = httpx.HTTPStatusError(
        "401", request=request, response=httpx.Response(401, request=request)
    )
    client, log = _client(
        environment, FakeSession(), open_error=ExceptionGroup("task group", [error])
    )
    result = _run(log, client.discover)
    assert result.state == "sign_in_required"


def test_failure_after_submit_dispatch_is_outcome_unknown(environment):
    session = FakeSession(call_error=ExceptionGroup("tg", [TimeoutError("read timed out")]))
    client, log = _client(environment, session)
    result = _run(
        log,
        lambda t: client.call_tool(
            "contribute_submit", {"kind": "vector", "manifest": {}}, t, allow_write=True
        ),
    )
    assert result.state == "outcome_unknown"
    assert len(session.calls) == 1


def test_failure_before_dispatch_is_plain_failure(environment):
    client, log = _client(environment, FakeSession(), open_error=ConnectionError("down"))
    result = _run(log, lambda t: client.call_tool("contribute_status", {}, t))
    assert result.state == "failed"


def test_missing_token_opens_no_session(environment):
    seen: dict = {}
    client, log = _client(environment, FakeSession(), seen=seen, tokens=FakeTokens(token=None))
    result = _run(log, client.discover)
    assert result.state == "sign_in_required"
    assert seen == {}

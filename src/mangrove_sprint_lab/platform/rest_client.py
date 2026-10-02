"""Hosted contribution REST API: submit and status only.

Contract (SIG runbook "Adding your own data", section 10, read 2 October 2026):

    POST {platform}/api/contribute            body = manifest (JSON here), `kind` at top level
    GET  {platform}/api/contribute/<id>       the record, for a contribution the person can see
    Authorization: Bearer <platform access token>
    401 + WWW-Authenticate when the token is missing or expired.

No other REST route is documented, so none is implemented. A POST that times out or loses its
connection after sending is `outcome_unknown` and is never retried: the platform may already have
accepted it and no idempotency key is documented.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from mangrove_sprint_lab.config import Environment
from mangrove_sprint_lab.platform.results import OperationResult
from mangrove_sprint_lab.platform.token_provider import SignInRequired, TokenProvider
from mangrove_sprint_lab.redact import redact, redact_text
from mangrove_sprint_lab.traces import Trace

CONTRIBUTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# The helper's own acceptance check asks about an id that cannot exist (grp-login.py `check`).
ACCEPTANCE_PROBE_ID = "0000000000000000"
USER_AGENT = "mangrove-sprint-lab/0.1 (+https://github.com/SERVIRSEA/mangrove-sprint-lab)"


def _strip(text: str | None, secrets: tuple[str, ...]) -> str | None:
    for secret in secrets:
        if text and secret:
            text = text.replace(secret, "***")
    return text or None


class RestContributionClient:
    adapter = "rest"

    def __init__(
        self,
        environment: Environment,
        tokens: TokenProvider,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.environment = environment
        self.tokens = tokens
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.environment.request_timeout,
            follow_redirects=False,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def _result(self, operation: str, state: str, **values: Any) -> OperationResult:
        return OperationResult(
            state=state,
            operation=operation,
            adapter=self.adapter,
            environment=self.environment.name,
            **values,
        )

    def _decode(self, operation: str, response: httpx.Response, trace: Trace) -> OperationResult:
        secrets = self.tokens.secrets()
        if response.status_code == 401:
            challenge = response.headers.get("www-authenticate")
            return self._result(
                operation,
                "sign_in_required",
                http_status=401,
                error="The platform did not accept the token (401). Refresh it with "
                "`python tools/grp-login.py token`, or sign in again with `login`.",
                # The challenge names the login metadata and carries no credential; keep it
                # intact, removing only a known token value should a server ever echo one.
                raw={"www_authenticate": _strip(challenge, secrets)},
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return self._result(
                operation,
                "failed",
                http_status=response.status_code,
                error="The platform returned a response that is not JSON.",
                raw=redact_text(response.text[:2000], secrets),
            )
        trace.platform_trace = payload.get("trace") if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            return self._result(
                operation,
                "failed",
                http_status=response.status_code,
                error="The platform returned JSON that is not an object.",
                raw=redact(payload, secrets),
            )
        if response.status_code >= 400 and payload.get("status") != "declined":
            return self._result(
                operation,
                "failed",
                http_status=response.status_code,
                error=f"The platform answered HTTP {response.status_code}.",
                data=redact(payload, secrets),
            )
        # approved / staged / declined (with every problem) are all answers: shown verbatim.
        return self._result(
            operation, "ok", http_status=response.status_code, data=redact(payload, secrets)
        )

    def submit(self, manifest: dict[str, Any], trace: Trace) -> OperationResult:
        operation = "contribute_submit"
        if not isinstance(manifest.get("kind"), str):
            return self._result(operation, "failed", error="The manifest needs a top-level kind.")
        try:
            token = self.tokens.access_token()
        except SignInRequired as error:
            return self._result(operation, "sign_in_required", error=str(error))
        url = self.environment.rest_contribute_url
        try:
            with self._client() as client:
                response = client.post(
                    url,
                    content=json.dumps(manifest).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            # The request never reached the server; nothing was accepted.
            trace.call(method="POST", url=url, error=type(error).__name__)
            return self._result(
                operation, "failed", error=f"Could not reach the platform ({type(error).__name__})."
            )
        except httpx.HTTPError as error:
            trace.call(method="POST", url=url, error=type(error).__name__)
            return self._result(
                operation,
                "outcome_unknown",
                error=(
                    f"The submit was sent but no answer arrived ({type(error).__name__}). The "
                    "platform may already hold it. Do NOT resend. Check your contributions with "
                    "MCP `contribute_status {}` (REST has no documented list route), or ask SIG."
                ),
            )
        trace.call(method="POST", url=url, status=response.status_code)
        return self._decode(operation, response, trace)

    def status(self, contribution_id: str, trace: Trace) -> OperationResult:
        operation = "contribute_status"
        if not CONTRIBUTION_ID.fullmatch(contribution_id):
            return self._result(operation, "failed", error="That is not a contribution id.")
        try:
            token = self.tokens.access_token()
        except SignInRequired as error:
            return self._result(operation, "sign_in_required", error=str(error))
        url = f"{self.environment.rest_contribute_url}/{contribution_id}"
        try:
            with self._client() as client:
                response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as error:
            trace.call(method="GET", url=url, error=type(error).__name__)
            return self._result(
                operation, "failed", error=f"Could not reach the platform ({type(error).__name__})."
            )
        trace.call(method="GET", url=url, status=response.status_code)
        return self._decode(operation, response, trace)

    def check_auth(self, trace: Trace) -> OperationResult:
        """Does the platform accept the token? Reads an id that cannot exist; creates nothing."""

        result = self.status(ACCEPTANCE_PROBE_ID, trace)
        result.operation = "check_auth"
        if result.state == "ok":
            result.notes.append("Token accepted by the hosted contribution API.")
        return result

    def probe_unauthenticated(self, trace: Trace) -> OperationResult:
        """Live check with no token: a 401 + WWW-Authenticate proves the route and the sign-in
        path, nothing more."""

        url = f"{self.environment.rest_contribute_url}/{ACCEPTANCE_PROBE_ID}"
        try:
            with self._client() as client:
                response = client.get(url)
        except httpx.HTTPError as error:
            trace.call(method="GET", url=url, error=type(error).__name__)
            return self._result(
                "probe", "failed", error=f"Could not reach the platform ({type(error).__name__})."
            )
        trace.call(method="GET", url=url, status=response.status_code)
        return self._decode("probe", response, trace)

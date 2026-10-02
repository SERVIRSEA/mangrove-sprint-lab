"""The common operations boundary. The UI/CLI calls this; it never talks to an adapter directly.

Rules:
- The transport is chosen once, by configuration. A failure never falls back to the other
  transport, another identity or another environment.
- An operation without a documented contract on the selected transport returns `unsupported`.
- Every executed operation writes a trace, including failures.
- A contribution is sent only through `submit`, behind explicit gates. Nothing submits at startup,
  in sample mode or in tests.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mangrove_sprint_lab.config import Environment
from mangrove_sprint_lab.contract import check_local_file, check_manifest, load_manifest
from mangrove_sprint_lab.platform.mcp_client import McpPlatformClient
from mangrove_sprint_lab.platform.rest_client import RestContributionClient
from mangrove_sprint_lab.platform.results import OperationResult
from mangrove_sprint_lab.platform.token_provider import TokenProvider
from mangrove_sprint_lab.redact import redact
from mangrove_sprint_lab.traces import TraceLog

POLL_MAX_ATTEMPTS = 10
POLL_MIN_INTERVAL = 5.0


class Operations:
    def __init__(
        self,
        environment: Environment,
        *,
        tokens: TokenProvider | None = None,
        rest: RestContributionClient | None = None,
        mcp: McpPlatformClient | None = None,
        sleep=time.sleep,
    ) -> None:
        self.environment = environment
        self.tokens = tokens or TokenProvider(environment)
        self.rest = rest or RestContributionClient(environment, self.tokens)
        self.mcp = mcp or McpPlatformClient(environment, self.tokens)
        self.traces = TraceLog(environment.outputs_dir)
        self._sleep = sleep

    @property
    def adapter(self) -> str:
        return self.environment.transport

    def _traced(self, operation: str, run) -> OperationResult:
        with self.traces.trace(operation, self.adapter, self.environment.name) as trace:
            result: OperationResult = run(trace)
            trace.outcome = result.state
            if result.error:
                trace.error = result.error
            result.trace_id = trace.trace_id
            return result

    def _unsupported(self, operation: str, why: str) -> OperationResult:
        def run(_trace) -> OperationResult:
            return OperationResult(
                "unsupported", operation, self.adapter, self.environment.name, error=why
            )

        return self._traced(operation, run)

    # ------------------------------------------------------------------ connection

    def describe(self) -> dict[str, Any]:
        """Configured environment and local readiness. Makes no network call, reads no token."""

        env = self.environment
        helper = env.helper_path
        return {
            "environment": env.name,
            "transport": env.transport,
            "platform_url": env.platform_url,
            "mcp_url": env.mcp_url,
            "rest_contribute_url": env.rest_contribute_url,
            "resource": env.resource,
            "login_helper": str(helper) if helper else None,
            "login_helper_installed": bool(helper and helper.is_file()),
            "connection": "offline (synthetic mode)" if env.is_offline else "not checked yet",
        }

    def check_auth(self) -> OperationResult:
        if self.environment.is_offline:
            return self._unsupported("check_auth", "Offline mode has no platform connection.")
        if self.adapter == "rest":
            return self._traced("check_auth", self.rest.check_auth)

        def run(trace) -> OperationResult:
            result = asyncio.run(self.mcp.discover(trace))
            result.operation = "check_auth"
            if result.ok:
                result.notes.append(f"MCP session opened; {len(self.mcp.tools)} tools advertised.")
            return result

        return self._traced("check_auth", run)

    def probe(self) -> OperationResult:
        """Unauthenticated live probe of the selected transport's endpoint (expects 401)."""

        if self.environment.is_offline:
            return self._unsupported("probe", "Offline mode has no platform connection.")
        if self.adapter == "rest":
            return self._traced("probe", self.rest.probe_unauthenticated)
        return self._traced("probe", lambda t: asyncio.run(self.mcp.probe_unauthenticated(t)))

    # ------------------------------------------------------------------ discovery (MCP)

    def discover(self) -> OperationResult:
        if self.adapter != "mcp":
            return self._unsupported(
                "discover", "Tool discovery is an MCP operation; no REST route is documented."
            )
        result = self._traced("discover", lambda t: asyncio.run(self.mcp.discover(t)))
        if result.ok:
            self._save_snapshot(result.data)
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> OperationResult:
        if self.adapter != "mcp":
            return self._unsupported(name, f"{name} is an MCP tool; no REST route is documented.")
        return self._traced(name, lambda t: asyncio.run(self.mcp.call_tool(name, arguments, t)))

    def read_resource(self, uri: str) -> OperationResult:
        if self.adapter != "mcp":
            return self._unsupported("read_resource", "Resources are read over MCP only.")
        return self._traced("read_resource", lambda t: asyncio.run(self.mcp.read_resource(uri, t)))

    def _save_snapshot(self, data: Any) -> None:
        path = self.environment.outputs_dir / "capability_snapshot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": self.environment.name,
            "mcp_url": self.environment.mcp_url,
            "discovered": data,
        }
        path.write_text(json.dumps(redact(snapshot), indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ contributions

    def preview(self, manifest_path: Path, data_file: Path | None = None) -> dict[str, Any]:
        """Everything a person must see before deciding to submit. Local; sends nothing."""

        document = load_manifest(manifest_path)
        checked = check_manifest(document)
        lab = document.get("x_lab") if isinstance(document.get("x_lab"), dict) else {}
        file_check = asdict(check_local_file(data_file)) if data_file else None
        endpoint = {
            "rest": self.environment.rest_contribute_url,
            "mcp": f"{self.environment.mcp_url} (tool contribute_submit)",
        }.get(self.adapter, "none (offline)")
        return {
            "environment": self.environment.name,
            "transport": self.adapter,
            "endpoint": endpoint,
            "operation": "contribute_submit",
            "manifest_file": str(manifest_path),
            "wire_manifest": redact(checked.wire_manifest()) if checked.kind else None,
            "source_reference": lab.get("source_reference"),
            "synthetic": bool(lab.get("synthetic")),
            "problems": checked.problems,
            "gaps": checked.gaps,
            "notes": checked.notes,
            "local_file_check": file_check,
            "ready_to_submit": checked.sendable and not self.environment.is_offline,
            "warning": "Submitting publishes under your own account. The platform may "
            "auto-approve, and names cannot be overwritten. Read docs/ACCEPTANCE.md first.",
        }

    def submit(
        self,
        manifest_path: Path,
        *,
        confirm_environment: str | None,
        allow_synthetic: bool = False,
        real_name: bool = False,
    ) -> OperationResult:
        """Send one contribution. Every gate must pass; a refused gate sends nothing."""

        document = load_manifest(manifest_path)
        checked = check_manifest(document)
        lab = document.get("x_lab") if isinstance(document.get("x_lab"), dict) else {}
        name = str(checked.manifest.get("layer") or checked.manifest.get("dataset") or "")

        refusal: str | None = None
        if self.environment.is_offline:
            refusal = "Offline mode cannot submit. Choose MSL_TRANSPORT=rest or mcp."
        elif not checked.sendable:
            refusal = "The manifest has problems or contract gaps; run preview."
        elif confirm_environment != self.environment.name:
            refusal = f"Type the environment name to confirm: --confirm {self.environment.name}"
        elif lab.get("synthetic") and not allow_synthetic:
            refusal = "This is a synthetic sample. Add --allow-synthetic only for a test layer."
        elif name and "_test" not in name and not real_name:
            refusal = "The name is not a test name (_test_<initials>). Add --real-name to send it."
        if refusal:
            return self._traced(
                "contribute_submit",
                lambda _t: OperationResult(
                    "failed", "contribute_submit", self.adapter, self.environment.name,
                    error=f"Not sent: {refusal}",
                ),
            )

        wire = checked.wire_manifest()
        if self.adapter == "rest":
            result = self._traced("contribute_submit", lambda t: self.rest.submit(wire, t))
        else:
            arguments = {"kind": checked.kind, "manifest": checked.manifest}

            async def run_mcp(trace) -> OperationResult:
                return await self.mcp.call_tool(
                    "contribute_submit", arguments, trace, allow_write=True
                )

            result = self._traced("contribute_submit", lambda t: asyncio.run(run_mcp(t)))
        self._record_submission(manifest_path, name, result)
        return result

    def _record_submission(self, manifest: Path, name: str, result: OperationResult) -> None:
        """Keep every send attempt, so two contributions are never confused later."""

        path = self.environment.outputs_dir / "contributions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = result.data if isinstance(result.data, dict) else {}
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": self.environment.name,
            "adapter": self.adapter,
            "manifest": str(manifest),
            "name": name,
            "state": result.state,
            "status": data.get("status"),
            "contribution_id": data.get("contribution_id"),
            "trace_id": result.trace_id,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def status(self, contribution_id: str) -> OperationResult:
        if self.environment.is_offline:
            return self._unsupported("contribute_status", "Offline mode has no platform.")
        if self.adapter == "rest":
            return self._traced("contribute_status", lambda t: self.rest.status(contribution_id, t))
        return self.call_tool("contribute_status", {"contribution_id": contribution_id})

    def poll(
        self, contribution_id: str, attempts: int = 5, interval: float = 15.0
    ) -> list[OperationResult]:
        """Bounded status polling; stops at the first answer that is no longer pending."""

        attempts = max(1, min(attempts, POLL_MAX_ATTEMPTS))
        interval = max(interval, POLL_MIN_INTERVAL)
        results: list[OperationResult] = []
        for attempt in range(attempts):
            result = self.status(contribution_id)
            results.append(result)
            if not result.ok or result.contribution_status() not in {None, "pending", "checking"}:
                break
            if attempt < attempts - 1:
                self._sleep(interval)
        return results

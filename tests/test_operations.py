from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from conftest import FakeTokens
from mangrove_sprint_lab.platform.mcp_client import McpPlatformClient
from mangrove_sprint_lab.platform.operations import Operations
from mangrove_sprint_lab.platform.rest_client import RestContributionClient

GOOD = """
kind: vector
layer: mangrove_plots_test_ab
url: https://example.org/plots.geojson
title: Test plots
description: Test points.
source: Test
license: CC0-1.0
vintage: "2026-10"
x_lab: {geometry: point}
"""


class ExplodingMcp:
    """Proves a REST failure never falls back to MCP."""

    def __getattr__(self, name):
        raise AssertionError(f"MCP adapter used: {name}")


def _ops(environment, transport="rest", handler=None, **env_changes):
    env = environment(transport, **env_changes)
    tokens = FakeTokens()
    handler = handler or (lambda r: httpx.Response(200, json={"status": "staged",
                                                               "contribution_id": "c9"}))
    rest = RestContributionClient(env, tokens, transport=httpx.MockTransport(handler))
    mcp = ExplodingMcp() if transport == "rest" else McpPlatformClient(env, tokens)
    return Operations(env, tokens=tokens, rest=rest, mcp=mcp, sleep=lambda _s: None)


@pytest.fixture
def manifest(tmp_path: Path):
    def write(text: str = GOOD, name: str = "m.yml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return write


def test_offline_mode_reports_unsupported_and_traces_it(environment):
    ops = _ops(environment, "offline")
    result = ops.check_auth()
    assert result.state == "unsupported"
    assert ops.traces.read()[-1]["outcome"] == "unsupported"


def test_rest_has_no_discovery_and_does_not_fall_back(environment):
    ops = _ops(environment, "rest")
    assert ops.discover().state == "unsupported"
    assert ops.call_tool("platform_capabilities", {}).state == "unsupported"
    assert ops.read_resource("servirplatform://skill/trace-emit").state == "unsupported"


def test_submit_without_confirmation_sends_nothing(environment, manifest):
    calls = []
    ops = _ops(environment, handler=lambda r: calls.append(r) or httpx.Response(200, json={}))
    result = ops.submit(manifest(), confirm_environment=None)
    assert result.state == "failed" and "Not sent" in result.error
    assert calls == []


def test_submit_refuses_wrong_environment_name(environment, manifest):
    ops = _ops(environment)
    result = ops.submit(manifest(), confirm_environment="production")
    assert "Not sent" in result.error


def test_submit_refuses_synthetic_and_real_names_without_flags(environment, manifest):
    ops = _ops(environment)
    synthetic = manifest(GOOD.replace("{geometry: point}", "{geometry: point, synthetic: true}"))
    assert "synthetic" in ops.submit(synthetic, confirm_environment="sig-hosted").error
    real = manifest(GOOD.replace("mangrove_plots_test_ab", "mangrove_plots"), name="r.yml")
    assert "test name" in ops.submit(real, confirm_environment="sig-hosted").error


def test_submit_refuses_a_contract_gap(environment, manifest):
    ops = _ops(environment)
    polygons = manifest(GOOD.replace("{geometry: point}", "{geometry: polygon}"))
    result = ops.submit(polygons, confirm_environment="sig-hosted")
    assert "contract gaps" in result.error


def test_offline_submit_is_refused(environment, manifest):
    ops = _ops(environment, "offline")
    assert "Offline" in ops.submit(manifest(), confirm_environment="sig-hosted").error


def test_confirmed_submit_is_sent_once_recorded_and_traced(environment, manifest):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "staged", "contribution_id": "c9"})

    ops = _ops(environment, handler=handler)
    result = ops.submit(manifest(), confirm_environment="sig-hosted")
    assert result.ok and result.contribution_status() == "staged"
    assert len(calls) == 1 and calls[0]["kind"] == "vector" and "x_lab" not in calls[0]
    record = json.loads(
        (ops.environment.outputs_dir / "contributions.jsonl").read_text().splitlines()[-1]
    )
    assert record["contribution_id"] == "c9" and record["trace_id"] == result.trace_id
    assert ops.traces.read()[-1]["outcome"] == "ok"


def test_poll_is_bounded_and_stops_when_not_pending(environment):
    answers = iter(["pending", "pending", "approved", "approved"])
    ops = _ops(environment, handler=lambda r: httpx.Response(200, json={"status": next(answers)}))
    results = ops.poll("abc", attempts=50, interval=0)
    assert [r.contribution_status() for r in results] == ["pending", "pending", "approved"]


def test_failed_operation_still_writes_a_trace(environment):
    ops = _ops(environment, handler=lambda r: httpx.Response(500, text="boom"))
    result = ops.status("abc")
    assert result.state == "failed"
    trace = ops.traces.read()[-1]
    assert trace["outcome"] == "failed" and trace["model_usage"]["status"] == "not_applicable"


def test_preview_shows_target_and_sends_nothing(environment, manifest):
    calls = []
    ops = _ops(environment, handler=lambda r: calls.append(r) or httpx.Response(200, json={}))
    preview = ops.preview(manifest())
    assert preview["endpoint"] == "https://servirplatform.sig-gis.com/api/contribute"
    assert preview["ready_to_submit"] is True
    assert calls == []

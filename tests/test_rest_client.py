from __future__ import annotations

import json

import httpx

from conftest import FAKE_TOKEN, FakeTokens
from mangrove_sprint_lab.platform.rest_client import RestContributionClient
from mangrove_sprint_lab.traces import TraceLog

MANIFEST = {"kind": "vector", "layer": "plots_test_ab", "url": "https://example.org/a.geojson"}


def _client(environment, handler, tokens=None):
    env = environment("rest")
    return (
        RestContributionClient(env, tokens or FakeTokens(), transport=httpx.MockTransport(handler)),
        TraceLog(env.outputs_dir),
    )


def _submit(environment, handler, tokens=None):
    client, log = _client(environment, handler, tokens)
    with log.trace("contribute_submit", "rest", "test") as trace:
        result = client.submit(dict(MANIFEST), trace)
    return result, log


def test_submit_sends_manifest_with_top_level_kind_and_bearer(environment):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["type"] = request.headers["content-type"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "approved", "contribution_id": "abc123"})

    result, _ = _submit(environment, handler)
    assert seen == {
        "method": "POST",
        "url": "https://servirplatform.sig-gis.com/api/contribute",
        "auth": f"Bearer {FAKE_TOKEN}",
        "type": "application/json",
        "body": MANIFEST,
    }
    assert result.ok and result.contribution_status() == "approved"
    assert result.data["contribution_id"] == "abc123"


def test_staged_is_reported_as_staged_not_approved(environment):
    result, _ = _submit(
        environment,
        lambda r: httpx.Response(200, json={"status": "staged", "contribution_id": "s1"}),
    )
    assert result.ok and result.contribution_status() == "staged"


def test_declined_keeps_every_problem_and_expected_fields(environment):
    payload = {
        "status": "declined",
        "problems": ["layer must be snake_case: 3-40 chars", "license is required"],
        "expected": {"vector": ["layer", "url", "title", "license"]},
    }
    result, _ = _submit(environment, lambda r: httpx.Response(422, json=payload))
    assert result.ok
    assert result.contribution_status() == "declined"
    assert result.data == payload


def test_401_is_sign_in_required_with_challenge(environment):
    challenge = 'Bearer resource_metadata="https://servirplatform.sig-gis.com/.well-known/x"'
    result, _ = _submit(
        environment,
        lambda r: httpx.Response(401, headers={"WWW-Authenticate": challenge}, text="no"),
    )
    assert result.state == "sign_in_required"
    assert result.http_status == 401
    assert result.raw["www_authenticate"] == challenge


def test_malformed_json_is_failed_and_keeps_masked_body(environment):
    result, _ = _submit(
        environment,
        lambda r: httpx.Response(200, text=f"<html>oops Bearer {FAKE_TOKEN}</html>"),
    )
    assert result.state == "failed"
    assert FAKE_TOKEN not in result.raw
    assert "<html>oops" in result.raw


def test_post_timeout_is_outcome_unknown_and_never_retried(environment):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    result, log = _submit(environment, handler)
    assert result.state == "outcome_unknown"
    assert "Do NOT resend" in result.error
    assert len(calls) == 1
    trace = log.read()[-1]
    assert trace["upstream"][0]["error"] == "ReadTimeout"


def test_connect_error_is_failed_because_nothing_was_sent(environment):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result, _ = _submit(environment, handler)
    assert result.state == "failed"


def test_missing_token_never_calls_the_platform(environment):
    calls = []
    tokens = FakeTokens(token=None)
    result, _ = _submit(environment, lambda r: calls.append(r) or httpx.Response(200), tokens)
    assert result.state == "sign_in_required"
    assert calls == []


def test_manifest_without_kind_is_refused_locally(environment):
    client, log = _client(environment, lambda r: httpx.Response(200, json={}))
    with log.trace("contribute_submit", "rest", "test") as trace:
        result = client.submit({"layer": "x"}, trace)
    assert result.state == "failed"


def test_status_uses_documented_get_route(environment):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, json={"status": "staged", "title": "t"})

    client, log = _client(environment, handler)
    with log.trace("contribute_status", "rest", "test") as trace:
        result = client.status("212436d83e490738", trace)
    assert seen == {
        "url": "https://servirplatform.sig-gis.com/api/contribute/212436d83e490738",
        "method": "GET",
    }
    assert result.contribution_status() == "staged"


def test_status_refuses_an_id_that_could_change_the_path(environment):
    client, log = _client(environment, lambda r: httpx.Response(200, json={}))
    with log.trace("contribute_status", "rest", "test") as trace:
        result = client.status("../admin", trace)
    assert result.state == "failed"


def test_token_never_reaches_results_or_traces(environment):
    payload = {"status": "approved", "echo": f"Bearer {FAKE_TOKEN}", "access_token": FAKE_TOKEN}
    result, log = _submit(environment, lambda r: httpx.Response(200, json=payload))
    assert FAKE_TOKEN not in json.dumps(result.data)
    assert FAKE_TOKEN not in log.path.read_text(encoding="utf-8")

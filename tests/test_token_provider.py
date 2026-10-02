from __future__ import annotations

import base64
import json
import subprocess
import time
from dataclasses import replace

import pytest

from mangrove_sprint_lab.platform.token_provider import SignInRequired, TokenProvider, token_info


def _jwt(claims: dict) -> str:
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.c2lnbmF0dXJlLXZhbHVl"


def _runner(stdout: str = "", returncode: int = 0, stderr: str = "", seen: list | None = None):
    def run(command, **kwargs):
        if seen is not None:
            seen.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    return run


@pytest.fixture
def helper(tmp_path):
    path = tmp_path / "grp-login.py"
    path.write_text("# stand-in helper\n", encoding="utf-8")
    return path


def test_missing_helper_means_sign_in_required(environment, tmp_path):
    env = replace(environment(), helper_path=tmp_path / "absent.py")
    with pytest.raises(SignInRequired, match="helper is not installed"):
        TokenProvider(env, runner=_runner("x")).access_token()


def test_helper_failure_is_sign_in_required_and_redacted(environment, helper):
    secret = "eyJabcdefgh.eyJpayloadxx.signaturexx"
    env = replace(environment(), helper_path=helper)
    runner = _runner(returncode=1, stderr=f"refresh failed for {secret} — log in again")
    with pytest.raises(SignInRequired) as caught:
        TokenProvider(env, runner=runner).access_token()
    assert secret not in str(caught.value)


def test_token_for_another_resource_is_refused(environment, helper):
    env = replace(environment(), helper_path=helper)
    token = _jwt({"aud": "https://other.example/mcp", "exp": time.time() + 3600})
    with pytest.raises(SignInRequired, match="another resource"):
        TokenProvider(env, runner=_runner(token + "\n")).access_token()


def test_valid_token_is_cached_and_helper_pinned_to_platform(environment, helper):
    env = replace(environment(), helper_path=helper)
    token = _jwt({"aud": env.resource, "exp": time.time() + 3600, "sub": "user_01ABCDWXYZ"})
    seen: list = []
    provider = TokenProvider(env, runner=_runner(token + "\n", seen=seen))
    assert provider.access_token() == token
    assert provider.access_token() == token
    assert len(seen) == 1
    command, kwargs = seen[0]
    assert command[-1] == "token"
    assert kwargs["env"]["GRP_PLATFORM"] == env.platform_url
    assert provider.info().subject_hint == "…WXYZ"


def test_token_near_expiry_is_fetched_again(environment, helper):
    env = replace(environment(), helper_path=helper)
    token = _jwt({"aud": env.resource, "exp": time.time() + 30})
    seen: list = []
    provider = TokenProvider(env, runner=_runner(token, seen=seen))
    provider.access_token()
    provider.access_token()
    assert len(seen) == 2


def test_opaque_token_gives_no_hints_but_is_accepted(environment, helper):
    env = replace(environment(), helper_path=helper)
    provider = TokenProvider(env, runner=_runner("opaque-token-value-123456"))
    assert provider.access_token() == "opaque-token-value-123456"
    assert token_info("opaque-token-value-123456").audience == ()

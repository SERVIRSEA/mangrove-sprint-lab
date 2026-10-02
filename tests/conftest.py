from __future__ import annotations

import socket
from dataclasses import replace
from pathlib import Path

import pytest

from mangrove_sprint_lab.config import load_environment

FAKE_TOKEN = "fake-token-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never reach a real platform, so no test can submit a real contribution."""

    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        # asyncio on Windows opens a loopback socket pair for its own event loop.
        host = address[0] if isinstance(address, tuple) else address
        if host in {"127.0.0.1", "::1", "localhost"}:
            return real_connect(self, address, *args, **kwargs)
        raise OSError("network disabled in tests")

    def refuse(*_args, **_kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def environment(tmp_path: Path):
    def make(transport: str = "rest", **changes):
        env = load_environment(
            {"MSL_TRANSPORT": transport, "MSL_OUTPUTS_DIR": str(tmp_path / "outputs")},
            dotenv=None,
        )
        return replace(env, **changes)

    return make


class FakeTokens:
    def __init__(self, token: str | None = FAKE_TOKEN, error: str | None = None) -> None:
        self.token = token
        self.error = error
        self.calls = 0

    def access_token(self) -> str:
        from mangrove_sprint_lab.platform.token_provider import SignInRequired

        self.calls += 1
        if self.error or not self.token:
            raise SignInRequired(self.error or "Sign-in required")
        return self.token

    def secrets(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()


@pytest.fixture
def tokens():
    return FakeTokens()

"""Platform access token from SIG's terminal helper, `grp-login.py`.

The helper performs the user-initiated device login and stores the token in `~/.grp/token.json`.
This module only asks it for the current token (`grp-login.py token`, which refreshes when due)
and keeps the value in memory. The token is never printed, logged, traced or returned to a UI.

This is a single-operator pattern: the token identifies the person who signed in. A shared web
app must not reuse one operator's cached token for everyone (see docs/CONNECTIONS.md).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from mangrove_sprint_lab.config import Environment
from mangrove_sprint_lab.redact import redact_text

# Ask the helper again shortly before expiry, the same skew idea as GRP's sig_connection.
RENEW_SKEW_SECONDS = 120


class SignInRequired(RuntimeError):
    """No usable platform token. The message says what the operator should do; never a secret."""


@dataclass(frozen=True)
class TokenInfo:
    """Non-secret facts about the token, safe to show."""

    audience: tuple[str, ...]
    expires_at: float | None
    subject_hint: str | None

    def seconds_remaining(self, now: float | None = None) -> int | None:
        if self.expires_at is None:
            return None
        return int(self.expires_at - (now or time.time()))


def _claims(token: str) -> dict:
    """Read JWT claims without verifying them. Used only for audience/expiry hints; the platform
    verifies the token itself. An opaque token simply yields no hints."""

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def token_info(token: str) -> TokenInfo:
    claims = _claims(token)
    audience = claims.get("aud", ())
    if isinstance(audience, str):
        audience = (audience,)
    expires = claims.get("exp")
    subject = claims.get("sub")
    return TokenInfo(
        audience=tuple(str(item) for item in audience),
        expires_at=float(expires) if isinstance(expires, (int, float)) else None,
        # Only the last four characters of the subject, enough to tell two accounts apart.
        subject_hint=f"…{str(subject)[-4:]}" if subject else None,
    )


class TokenProvider:
    """Gets the operator's token through the helper. `runner` is replaceable for tests."""

    def __init__(self, environment: Environment, runner=subprocess.run) -> None:
        self.environment = environment
        self._runner = runner
        self._token: str | None = None
        self._info: TokenInfo | None = None

    @property
    def helper(self) -> Path | None:
        return self.environment.helper_path

    def _from_helper(self) -> str:
        helper = self.helper
        if helper is None or not helper.is_file():
            raise SignInRequired(
                "Sign-in required: the login helper is not installed. Run "
                "`uv run python scripts/fetch_grp_login.py`, then "
                "`python tools/grp-login.py login` in your own terminal."
            )
        try:
            completed = self._runner(
                [sys.executable, str(helper), "token"],
                capture_output=True,
                text=True,
                timeout=60,
                # The helper reads GRP_PLATFORM; pin it to the selected environment.
                env={**os.environ, "GRP_PLATFORM": self.environment.platform_url},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SignInRequired(f"Sign-in required: the helper did not run ({error}).") from error
        token = (completed.stdout or "").strip()
        if completed.returncode != 0 or not token or any(char.isspace() for char in token):
            reason = redact_text((completed.stderr or "").strip(), (token,))[:300]
            raise SignInRequired(
                "Sign-in required: the helper has no usable token"
                + (f" ({reason})" if reason else "")
                + ". Run `python tools/grp-login.py login` in your own terminal."
            )
        return token

    def access_token(self) -> str:
        """The current token, for the adapters only. Never show it."""

        if self._token and self._info and self._info.expires_at is not None:
            remaining = self._info.seconds_remaining()
            if remaining is not None and remaining > RENEW_SKEW_SECONDS:
                return self._token
        token = self._from_helper()
        info = token_info(token)
        if info.audience and self.environment.resource not in info.audience:
            raise SignInRequired(
                "Sign-in required: the stored token was minted for another resource "
                f"({', '.join(info.audience)}), not {self.environment.resource}."
            )
        self._token, self._info = token, info
        return token

    def info(self) -> TokenInfo | None:
        return self._info

    def secrets(self) -> tuple[str, ...]:
        """Values that redaction must remove, for adapters that build error text."""

        return (self._token,) if self._token else ()

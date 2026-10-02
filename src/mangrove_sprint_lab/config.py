"""Environment and transport configuration.

Values come from the process environment, optionally seeded from a local `.env` file. Nothing
here holds a credential: the platform token is fetched on demand by `platform.token_provider`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TRANSPORTS = ("rest", "mcp", "offline")
DEFAULT_PLATFORM = "https://servirplatform.sig-gis.com"


class ConfigError(ValueError):
    """The configuration is incomplete or unsafe; the message names the setting."""


@dataclass(frozen=True)
class Environment:
    """One named platform environment. Selecting it never changes identity or transport."""

    name: str
    transport: str
    platform_url: str
    mcp_url: str
    rest_contribute_url: str
    resource: str
    helper_path: Path | None
    outputs_dir: Path
    request_timeout: float

    @property
    def is_offline(self) -> bool:
        return self.transport == "offline"


def load_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE lines. Existing process variables always win."""

    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _https(url: str, setting: str) -> str:
    parsed = urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if not parsed.hostname or parsed.username or parsed.password:
        raise ConfigError(f"{setting} is not a valid URL")
    if parsed.scheme != "https" and not local:
        raise ConfigError(f"{setting} must use HTTPS")
    return url.rstrip("/")


def load_environment(
    env: dict[str, str] | None = None, *, dotenv: Path | None = Path(".env")
) -> Environment:
    source: dict[str, str] = {}
    if dotenv is not None:
        source.update(load_dotenv(dotenv))
    source.update(env if env is not None else dict(os.environ))

    transport = source.get("MSL_TRANSPORT", "offline").strip().lower()
    if transport not in TRANSPORTS:
        raise ConfigError(f"MSL_TRANSPORT must be one of {', '.join(TRANSPORTS)}")
    platform = _https(source.get("MSL_PLATFORM_URL", DEFAULT_PLATFORM), "MSL_PLATFORM_URL")
    helper = source.get("MSL_GRP_LOGIN_HELPER", "").strip()
    try:
        timeout = float(source.get("MSL_REQUEST_TIMEOUT", "60"))
    except ValueError as error:
        raise ConfigError("MSL_REQUEST_TIMEOUT must be a number of seconds") from error
    return Environment(
        name=source.get("MSL_ENVIRONMENT", "sig-hosted").strip() or "sig-hosted",
        transport=transport,
        platform_url=platform,
        mcp_url=_https(source.get("MSL_MCP_URL", f"{platform}/mcp"), "MSL_MCP_URL"),
        rest_contribute_url=_https(
            source.get("MSL_REST_CONTRIBUTE_URL", f"{platform}/api/contribute"),
            "MSL_REST_CONTRIBUTE_URL",
        ),
        # The audience the platform verifies; the runbook and the helper both name /mcp.
        resource=_https(source.get("MSL_RESOURCE", f"{platform}/mcp"), "MSL_RESOURCE"),
        helper_path=Path(helper) if helper else Path("tools/grp-login.py"),
        outputs_dir=Path(source.get("MSL_OUTPUTS_DIR", "outputs")),
        request_timeout=timeout,
    )

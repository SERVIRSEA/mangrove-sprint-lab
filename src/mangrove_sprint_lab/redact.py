"""Remove credentials and signed-URL secrets from anything that is shown, logged or traced."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

MASK = "***"
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_URL = re.compile(r"https?://[^\s\"'<>]+")
# Query parameters that carry a signature or credential in common signed-URL schemes.
SECRET_PARAMS = re.compile(
    r"(?i)^(x-amz-(signature|credential|security-token)|x-goog-(signature|credential)|"
    r"signature|sig|se|sp|sv|st|skoid|sktid|skt|ske|sks|skv|token|access_token|"
    r"api[_-]?key|key|code|password|expires|googleaccessid|policy|key-pair-id)$"
)
SECRET_KEYS = re.compile(
    r"(?i)(access_token|refresh_token|id_token|authorization|password|secret|api[_-]?key|"
    r"device_code|client_secret)"
)


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query and not parsed.password:
        return url
    query = [
        (key, MASK if SECRET_PARAMS.match(key) else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    netloc = parsed.netloc
    if parsed.password:
        netloc = netloc.replace(f":{parsed.password}@", f":{MASK}@")
    return urlunparse(parsed._replace(netloc=netloc, query=urlencode(query, safe="*")))


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, MASK)
    text = _BEARER.sub(lambda match: match.group(1) + MASK, text)
    text = _JWT.sub(MASK, text)
    return _URL.sub(lambda match: redact_url(match.group(0)), text)


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Return a copy of a JSON-like value with secrets masked; the original is untouched."""

    if isinstance(value, dict):
        return {
            key: MASK if SECRET_KEYS.search(str(key)) and value_present(item)
            else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def value_present(value: Any) -> bool:
    return value not in (None, "", [], {})

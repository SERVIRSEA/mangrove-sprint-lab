"""Download SIG's terminal login helper into tools/ (git-ignored) and show its SHA-256.

The helper states no licence, so this repository does not redistribute it. Read it before you
run it; compare the hash with docs/CONNECTIONS.md and note any change.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://servirplatform.sig-gis.com/runbook/samples/grp-login.py"
TARGET = Path("tools/grp-login.py")


def main() -> int:
    request = urllib.request.Request(URL, headers={"User-Agent": "mangrove-sprint-lab/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    if not body.startswith(b"#!/usr/bin/env python3"):
        print("Unexpected content; not saved.", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(body)
    print(f"Saved {TARGET} ({len(body)} bytes)")
    print(f"SHA-256 {hashlib.sha256(body).hexdigest()}")
    print("Read it, then sign in from your own terminal: python tools/grp-login.py login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

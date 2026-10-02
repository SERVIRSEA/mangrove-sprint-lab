# Mangrove Sprint Lab: instructions for coding agents

Read `README.md`, then `docs/ACCEPTANCE.md` (what is verified) and `docs/SPRINT_NOTES.md`
(open questions). Update both at the end of each work session.

## Ground rules

- **Never submit a contribution** unless the user explicitly picks a permitted sample and asks
  for that one submit. Tests, the demo and startup must never submit. The tests block the
  network; keep it that way.
- Never print, log, trace or commit a token. The token stays in `~/.grp/` and is fetched only by
  `platform/token_provider.py`. Do not read `~/.grp/token.json` directly.
- Transport is explicit (`MSL_TRANSPORT`). Never fall back from one transport, identity or
  environment to another.
- Do not invent REST routes from MCP tool names. Add an operation only when its contract is
  documented, and cite the source in `docs/CONNECTIONS.md`.
- Do not invent science or provenance. A method stays `pending` until the team agrees it. A
  catalogue field stays `unconfirmed` until the publisher confirms it. Do not reclassify or
  rename mangrove data to fit a risk-pack contract; report the gap.
- Keep fixture-tested and live-verified behaviour separate in docs. Claim a live result only
  after it ran.
- This repository is **public**. Commit no internal document links, personal data, real
  restricted datasets or account details.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check .
uv run msl demo
```

## Where things are

- `src/mangrove_sprint_lab/platform/operations.py`: the one boundary the CLI uses.
- `rest_client.py` and `mcp_client.py`: the two adapters. Both return `OperationResult`
  (`results.py`).
- `contract.py`: local manifest rules (ported from GRP) and the mangrove gaps.
- `workflows/mangrove_step1.py`: experiment record and source checks.

## Handover (2 October 2026)

- Bootstrapped from SIG's runbook and GRP's proven patterns. Python 3.12, uv, MCP SDK 1.30
  (pinned below 2.0; reason in CONNECTIONS.md).
- **Live:** only unauthenticated 401 probes of both endpoints. The REST 401 has no
  `WWW-Authenticate`, although the runbook says it should.
- **Next:**
  1. The operator signs in with `grp-login.py`.
  2. Run `auth check`, then `discover`, then read `trace-emit`. Record the results in
     `CAPABILITY_SNAPSHOT.md`.
  3. Choose the real experiment area and sources with the team.
  4. Then decide on a local UI: a small FastAPI page on 127.0.0.1 over `Operations`.
  5. Optional question orchestration comes last, and must report model usage honestly.

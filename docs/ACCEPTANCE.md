# Acceptance

This file lists what has been verified, how, and what is still open. It is updated whenever
something new is run live.

## Status on 2 October 2026 (initial commit)

| Area | Status | Evidence |
|---|---|---|
| Separate repository; GRP untouched | Done | Built in its own directory and Git repository |
| Fresh install + offline demo | Done | `uv sync`, `uv run msl demo`; run again from a fresh clone |
| Tests, network blocked | 57 pass | `uv run pytest` |
| REST submit/status | **Fixture-tested** | `approved`, `staged`, `declined` (every problem kept), 401, malformed JSON, POST timeout (`outcome_unknown`, one request), connect error, bad id, token masking |
| MCP adapter | **Fixture-tested** | Discovery, schema validation, allowlist, 401 inside an exception group, failure after a submit was sent (`outcome_unknown`), no session without a token |
| Token provider | **Fixture-tested** | Missing helper, helper failure (masked), wrong audience, caching, near-expiry refresh |
| Live: REST endpoint | Unauthenticated 401 only | `msl probe` with `MSL_TRANSPORT=rest` |
| Live: MCP endpoint | Unauthenticated 401 + `WWW-Authenticate` | `msl probe` with `MSL_TRANSPORT=mcp` |
| Live: sign-in, `auth check`, `discover`, read-only tool | **Not run** | Needs the operator's login |
| Live contribution | **Not tested** | — |
| Mangrove contract or analysis | **Not available** | See SPRINT_NOTES.md |
| No automatic contribution | Done | Startup, demo and tests cannot submit; tests block the network |

## Before any live submit

1. Agree the sample and its name with the team. Use `<name>_test_<initials>` until a real layer
   is approved for sending.
2. Run `msl check` and read every problem, gap and note.
3. Remember that the platform may auto-approve. In that case the layer is public at once, and only
   a reviewer can withdraw it.
4. Submit once. If the result is `outcome_unknown`, do **not** resend. Check
   `contribute_status {}` over MCP.
5. Record the environment, the account, the contribution id and the reply (stored automatically
   in `outputs/contributions.jsonl`), then update this file.

## The next live checks, in order

1. `python tools/grp-login.py login` (operator, in their own terminal).
2. `MSL_TRANSPORT=rest uv run msl auth check`. This creates nothing.
3. `MSL_TRANSPORT=mcp uv run msl discover`. Record the result in CAPABILITY_SNAPSHOT.md.
4. `MSL_TRANSPORT=mcp uv run msl tool platform_capabilities`.
5. `MSL_TRANSPORT=mcp uv run msl resource servirplatform://skill/trace-emit`.

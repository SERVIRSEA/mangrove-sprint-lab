# Connections

This file records how the lab reaches the SERVIR platform, which contracts it relies on, and
where each one came from.

## Environments

There is one configured environment, `sig-hosted`:

| Setting | Value |
|---|---|
| Platform | `https://servirplatform.sig-gis.com` |
| MCP endpoint | `https://servirplatform.sig-gis.com/mcp` (streamable HTTP) |
| REST contribution | `https://servirplatform.sig-gis.com/api/contribute` |
| Token resource (audience) | `https://servirplatform.sig-gis.com/mcp` |

To add an environment, set the `MSL_*` variables in `.env`. The environment name is printed on
every result and must be typed to confirm a submit.

## Three kinds of credential

| Credential | Used for | Where it lives |
|---|---|---|
| **Platform access token** | REST and MCP calls. It identifies the contributing person. | `~/.grp/token.json`, written by SIG's helper |
| **MCP authentication** | The same platform token, sent as `Authorization: Bearer` to `/mcp` | Same as above |
| **Model-provider API key** | Optional question orchestration (not built yet) | Not used by this lab |

A model-provider key can never stand in for the platform token. Claude Desktop's or Claude
Code's own SERVIR connection is a different client. It does not give this application a login.

## Platform token: SIG's terminal helper

- Source: <https://servirplatform.sig-gis.com/runbook/samples/grp-login.py>, read 2 October 2026.
- SHA-256 on that date: `d7f1181d008037162729f567b08c4af02aaccbf4d51394ac56b9bbf17b519ff8`.
- Licence: none stated, so it is **not vendored**. `scripts/fetch_grp_login.py` downloads it
  to `tools/`, which Git ignores. Compare the hash and read the file before running it.
- Flow: OAuth 2.0 device authorization against the issuer that the platform's
  `/.well-known/oauth-protected-resource/mcp` names. The token is minted for the `/mcp` resource.
  The helper registers a public client once, or takes `--client-id`.
- Commands:
  - `login` runs `start` and then `finish`;
  - `token` prints the current token, refreshing it if needed;
  - `check` makes a GET for an id that cannot exist;
  - `start` and `finish` split the login into two steps.
- `TokenProvider` runs `grp-login.py token` with `GRP_PLATFORM` pinned to the selected
  environment. It keeps the token in memory, refuses a JWT whose `aud` is a different resource,
  and asks again 120 seconds before expiry.
- This is a **single-operator** pattern. A shared web app must give each user their own login,
  through the OAuth flow with a callback URL registered on the platform's AuthKit application.
  That registration has to be arranged with SIG, and the browser flow is not built.
- There is no service-account login. The runbook says so; nothing here runs unattended.

## REST contribution API

Source: the runbook ["Adding your own data", section 10](https://servirplatform.sig-gis.com/runbook/adding-your-own-data.html),
read 2 October 2026.

| Operation | Contract |
|---|---|
| Submit | `POST /api/contribute`. The body is the manifest with `kind` at the top. JSON is used here; YAML or multipart `file` is also documented. |
| Status | `GET /api/contribute/<contribution_id>` |
| Answers | `approved` or `staged` with a `contribution_id`; `declined` with every problem. Shown verbatim. |
| No token | 401 |

**Observed difference (2 October 2026):** the runbook says a 401 carries `WWW-Authenticate`.
Unauthenticated, the REST route answered `401 {"detail":"login required"}` **without** that
header. The MCP endpoint did send
`WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"`.
The client handles both.

No other REST route is documented: no capability list, no list of your contributions, no
questions, no analysis. Those operations return `unsupported` on REST. An MCP tool name is never
turned into a URL.

**Ambiguous submit:** after a timeout or a lost connection on POST, the result is
`outcome_unknown` and nothing is retried. No idempotency key is documented. Recover with MCP
`contribute_status {}`, which lists your contributions, or ask SIG.

## MCP

- Transport: streamable HTTP with a bearer token. This is the transport GRP uses in production
  (`api/mcp_client.py`, protocol `2025-06-18`). stdio is not offered, because no server command
  is known for the hosted platform.
- SDK: the official `mcp` Python SDK, **pinned below 2.0** (1.30.0 in `uv.lock`). Version 2.x
  reworks the client (`httpx2`, `mcp_types`, new negotiation modes). The server reports
  `0.2.0-phase1`, so the stable 1.x line is used, and all imports come from that one major
  version.
- Arguments are validated against the `inputSchema` the server advertised in the same session,
  before any call.
- Tools are allowlisted:
  - `platform_capabilities`, `contribute_status` and `feeds_query` are read-only;
  - `contribute_submit` is reached only through `msl submit`.

  Anything else returns `unsupported` until someone reviews it and adds it to `READ_ONLY_TOOLS`.
- `contribute_submit` arguments are `{"kind": ..., "manifest": {...}}`, as GRP sends them. The
  REST body is the manifest itself with `kind` at the top.

## Traces

- `outputs/traces/traces.jsonl` gets one line per operation, including failures. Each line has
  the trace id, operation, adapter, environment, duration, outcome, upstream calls (masked) and
  model usage.
- Model usage is `complete`, `partial`, `unavailable` or `not_applicable`. Missing usage is never
  recorded as zero.
- A `trace` field in a platform reply is kept as `platform_trace`.
- **Gap:** the platform's `servirplatform://skill/trace-emit` and `trace-visualize` resources have
  not been read. They need an authenticated MCP session. Run
  `msl resource servirplatform://skill/trace-emit` once signed in, and align traces with them.

## Code reused from GRP

The source is the ADPC GRP repository at commit `14e4993` (2 October 2026). It has no licence
file, and the owner authorised the reuse. Only patterns were ported:

| Here | From GRP | What |
|---|---|---|
| `contract.py` | `core/contribution_rules.py` | Required fields per kind, the 3-40 character layer rule, Drive link conversion, contact-field check |
| `platform/mcp_client.py` | `api/mcp_client.py` | Endpoint, bearer and protocol choice. 401/403 mean sign-in required. (The protocol itself is now handled by the SDK.) |
| `platform/token_provider.py` | `api/sig_connection.py` | Renewing a token shortly before it expires |
| `traces.py` | `api/langfuse.py` | Safe-fields-only trace records |

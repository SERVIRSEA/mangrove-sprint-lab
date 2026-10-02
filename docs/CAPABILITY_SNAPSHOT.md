# Capability snapshot

Refresh this file with `uv run msl discover`, which writes `outputs/capability_snapshot.json`.
Copy the parts that matter into this file, with the date.

## 2 October 2026: from a chat client, not from this application

The user's chat client inspected the MCP connected to it and reported:

- server `servirplatform`, version `0.2.0-phase1`, transport `stdio` in that host;
- domain packs `food-security` and `risk`, and **no mangrove pack**;
- available tools: `platform_capabilities`, `contribute_submit`, `contribute_status`,
  `feeds_query`, `assemble_pack`, `compose_run`, `publish_answer`, and other evidence and UI tools;
- `compute_run` listed as **planned**, not available.

This is evidence about that one host's connection only. This application has **not** yet listed
tools itself, because that needs the operator's sign-in.

## 2 October 2026: what this application observed (no token)

| Endpoint | Result |
|---|---|
| `POST https://servirplatform.sig-gis.com/mcp` (tools/list) | 401, `WWW-Authenticate: Bearer resource_metadata="https://servirplatform.sig-gis.com/.well-known/oauth-protected-resource/mcp"` |
| `GET https://servirplatform.sig-gis.com/api/contribute/0000000000000000` | 401, `{"detail":"login required"}`, no `WWW-Authenticate` |

## Next refresh

When the operator is signed in:

```bash
MSL_TRANSPORT=mcp uv run msl discover
MSL_TRANSPORT=mcp uv run msl tool platform_capabilities
MSL_TRANSPORT=mcp uv run msl resource servirplatform://skill/trace-emit
```

Then record the date, the environment, the tool names and their schemas, and whether a mangrove
pack or a mangrove contribution kind exists.

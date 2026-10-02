# Mangrove Sprint Lab

This is a small client for experimenting with the SERVIR platform during the mangrove development
sprint. It can:

- connect to the hosted platform over MCP or the documented contribution REST API;
- record and check one mangrove experiment locally;
- preview a contribution manifest and show where mangrove data has no accepted contract yet;
- submit one contribution behind explicit gates, then follow its status;
- keep a local trace of every operation.

It is a starting point, not a mangrove platform. No mangrove analysis method is implemented,
because the sprint team has not agreed one. See [what is verified](#what-is-verified) before you
rely on anything here.

## Install

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env        # optional; defaults to offline mode
uv run msl env
```

## Try it offline (no credentials)

```bash
uv run msl demo             # synthetic walk-through; sends nothing
uv run msl prepare          # record + check the example experiment
uv run msl check data/examples/manifests/synthetic_plots_points.yml --file data/examples/synthetic_plots.geojson
uv run msl traces
```

All example data is **synthetic**: invented shapes near 0°, 0°. It is not evidence and does not
describe any real place.

## Connect to the platform

1. Get SIG's login helper and read it. It is not redistributed here, because it states no
   licence.

   ```bash
   uv run python scripts/fetch_grp_login.py
   ```

2. Sign in from **your own terminal**. You open a link, check the code and approve:

   ```bash
   python tools/grp-login.py login
   ```

3. Choose a transport in `.env`, either `MSL_TRANSPORT=rest` or `MSL_TRANSPORT=mcp`, then run:

   ```bash
   uv run msl probe            # no token; expects 401 (proves the endpoint)
   uv run msl auth check       # with your token; creates nothing
   uv run msl discover         # MCP only: tools, schemas, resources -> outputs/capability_snapshot.json
   uv run msl tool platform_capabilities
   uv run msl resource servirplatform://skill/trace-emit
   ```

The token stays in `~/.grp/token.json`. This lab asks the helper for it when needed and never
prints, logs or traces it.

## Submit (read this first)

Submitting **publishes under your own account**. The platform has auto-approved contributions in
some sessions, and a name cannot be overwritten. Read [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)
before you submit anything.

```bash
uv run msl check  path/to/manifest.yml
uv run msl submit path/to/manifest.yml --confirm sig-hosted        # + --allow-synthetic / --real-name
uv run msl status <contribution_id> --poll 5 --interval 15
```

A submit is refused unless:

- you are not in offline mode;
- the manifest has no problems and no contract gaps;
- you type the environment name;
- the name is a `_test_` name (or you pass `--real-name`);
- the data is not synthetic (or you pass `--allow-synthetic`).

A submit that times out is reported as `outcome_unknown` and is never retried.

## Check the code

```bash
uv run pytest
uv run ruff check .
```

The tests block every non-loopback network connection, so they cannot reach the platform.

## Layout

```text
src/mangrove_sprint_lab/
  config.py                 environment + transport selection
  contract.py               manifest checks (ported from GRP) + mangrove contract gaps
  redact.py                 masking for tokens and signed URLs
  traces.py                 local JSONL traces, model-usage status
  platform/
    token_provider.py       token from SIG's grp-login.py helper
    rest_client.py          POST /api/contribute, GET /api/contribute/<id>
    mcp_client.py           official MCP SDK, streamable HTTP + bearer
    operations.py           the common boundary; no transport fallback
    results.py              one result shape for every operation
  workflows/mangrove_step1.py   experiment record + source checks (no method)
  application/cli.py        the `msl` command
data/                       synthetic examples, source catalogue, example experiment
docs/                       CONNECTIONS, CAPABILITY_SNAPSHOT, SPRINT_NOTES, ACCEPTANCE
outputs/                    traces and results (ignored by Git)
```

## What is verified

| Item | Status (2 October 2026) |
|---|---|
| Offline demo, preparation, manifest checks | Run and tested |
| REST submit/status client | Fixture-tested only; no live submit made |
| REST endpoint reachable, 401 without a token | Live-checked, unauthenticated |
| MCP endpoint reachable, 401 + `WWW-Authenticate` without a token | Live-checked, unauthenticated |
| Sign-in, `auth check`, `discover`, a read-only tool call | **Not yet run**: needs the operator's login |
| Live contribution | **Not tested** |
| Mangrove contribution contract or analysis | **Does not exist yet**: see docs/SPRINT_NOTES.md |

"""`msl`: the Mangrove Sprint Lab command line.

Every command prints JSON. A command that did not succeed exits non-zero. No command prints a
token, and only `submit` (with its explicit gates) can create a contribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mangrove_sprint_lab.config import ConfigError, load_environment
from mangrove_sprint_lab.platform.operations import Operations
from mangrove_sprint_lab.platform.results import OperationResult

EXAMPLES = Path("data/examples")
SAMPLE_EXPERIMENT = Path("data/experiments/synthetic_example.yml")
CATALOG = Path("data/source_catalog.yml")


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _emit(result: OperationResult | list[OperationResult]) -> int:
    results = result if isinstance(result, list) else [result]
    _print([asdict(item) for item in results] if isinstance(result, list) else asdict(result))
    return 0 if all(item.ok for item in results) else 1


def demo(ops: Operations) -> int:
    """Offline walk-through on synthetic data. Sends nothing, needs no credentials."""

    _print({"step": "1. environment", **ops.describe()})
    report = ops.prepare(SAMPLE_EXPERIMENT, CATALOG)
    _print({"step": "2. prepare the synthetic experiment", **report})
    for manifest in sorted((EXAMPLES / "manifests").glob("*.yml")):
        data_file = None
        target = manifest.read_text(encoding="utf-8")
        for candidate in EXAMPLES.glob("*.geojson"):
            if candidate.name in target:
                data_file = candidate
        preview = ops.preview(manifest, data_file)
        _print({"step": f"3. check {manifest.name}", **preview})
    _print({"step": "4. recent traces", "traces": ops.traces.read(5)})
    print(
        "\nSYNTHETIC DEMO: nothing was sent to any platform. These samples are not evidence.",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msl", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("env", help="show the configured environment (no network)")
    commands.add_parser("demo", help="offline synthetic walk-through")
    commands.add_parser("probe", help="unauthenticated live probe; expects 401")
    auth = commands.add_parser("auth", help="sign-in state")
    auth.add_argument("action", choices=["check"])
    commands.add_parser("discover", help="MCP: refresh tools, schemas and resources")
    tool = commands.add_parser("tool", help="MCP: call a reviewed read-only tool")
    tool.add_argument("name")
    tool.add_argument("--args", default="{}", help="JSON object of arguments")
    resource = commands.add_parser("resource", help="MCP: read a resource by URI")
    resource.add_argument("uri")
    prep = commands.add_parser("prepare", help="record and check an experiment locally")
    prep.add_argument("experiment", type=Path, nargs="?", default=SAMPLE_EXPERIMENT)
    prep.add_argument("--catalog", type=Path, default=CATALOG)
    check = commands.add_parser("check", help="preview a manifest; sends nothing")
    check.add_argument("manifest", type=Path)
    check.add_argument("--file", type=Path, help="local data file to check as well")
    submit = commands.add_parser("submit", help="send ONE contribution (explicit gates)")
    submit.add_argument("manifest", type=Path)
    submit.add_argument("--confirm", help="type the environment name to confirm")
    submit.add_argument("--allow-synthetic", action="store_true")
    submit.add_argument("--real-name", action="store_true", help="name is not a _test_ name")
    status = commands.add_parser("status", help="contribution status by id")
    status.add_argument("contribution_id")
    status.add_argument("--poll", type=int, default=1, help="attempts (max 10)")
    status.add_argument("--interval", type=float, default=15.0, help="seconds (min 5)")
    traces = commands.add_parser("traces", help="recent local traces")
    traces.add_argument("-n", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        environment = load_environment()
    except ConfigError as error:
        _print({"state": "unconfigured", "error": str(error)})
        return 2
    ops = Operations(environment)

    if args.command == "env":
        _print(ops.describe())
        return 0
    if args.command == "demo":
        return demo(ops)
    if args.command == "probe":
        result = ops.probe()
        _print(asdict(result))
        # The expected live answer without a token is 401 (sign_in_required).
        return 0 if result.state == "sign_in_required" else 1
    if args.command == "auth":
        return _emit(ops.check_auth())
    if args.command == "discover":
        return _emit(ops.discover())
    if args.command == "tool":
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError:
            _print({"state": "failed", "error": "--args must be a JSON object"})
            return 2
        return _emit(ops.call_tool(args.name, arguments))
    if args.command == "resource":
        return _emit(ops.read_resource(args.uri))
    if args.command == "prepare":
        _print(ops.prepare(args.experiment, args.catalog))
        return 0
    if args.command == "check":
        preview = ops.preview(args.manifest, args.file)
        _print(preview)
        return 0 if not preview["problems"] and not preview["gaps"] else 1
    if args.command == "submit":
        return _emit(
            ops.submit(
                args.manifest,
                confirm_environment=args.confirm,
                allow_synthetic=args.allow_synthetic,
                real_name=args.real_name,
            )
        )
    if args.command == "status":
        return _emit(ops.poll(args.contribution_id, args.poll, args.interval))
    if args.command == "traces":
        _print(ops.traces.read(args.n))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

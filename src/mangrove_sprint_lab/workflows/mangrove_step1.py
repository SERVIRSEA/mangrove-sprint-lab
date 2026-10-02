"""Step 1 of a mangrove experiment: record the question and check the sources locally.

This prepares; it does not analyse. The method stays `pending` until the sprint team agrees it,
and missing source metadata stays missing. Nothing is uploaded or submitted from here.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mangrove_sprint_lab.contract import check_local_file

CATALOG_FIELDS = (
    "id", "title", "owner_publisher", "link_or_path", "version_date", "coverage", "format",
    "crs", "resolution", "units_or_legend", "licence", "access_restrictions", "intended_use",
    "validation_status", "workflow_step",
)
EXPERIMENT_FIELDS = ("experiment_id", "area", "question", "dates", "expected_output", "method")
# Values that mean "someone still has to find this out". They are reported, never filled in.
UNKNOWN = {None, "", "unconfirmed", "unknown", "tbd", "to confirm", "pending"}


def _unknown(value: Any) -> bool:
    return isinstance(value, (str, type(None))) and str(value or "").strip().lower() in UNKNOWN


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_catalog_entry(entry: dict[str, Any], base: Path) -> dict[str, Any]:
    missing = [key for key in CATALOG_FIELDS if key not in entry]
    unknown = [key for key in CATALOG_FIELDS if key in entry and _unknown(entry[key])]
    file_check = None
    link = str(entry.get("link_or_path") or "")
    if link and not link.startswith(("http://", "https://")) and not _unknown(link):
        file_check = asdict(check_local_file((base / link).resolve()))
    return {
        "id": entry.get("id"),
        "synthetic": bool(entry.get("synthetic")),
        "missing_fields": missing,
        "unconfirmed_fields": unknown,
        "local_file_check": file_check,
        "remote_link_checked": False if link.startswith(("http://", "https://")) else None,
    }


def prepare(experiment_path: Path, catalog_path: Path, outputs_dir: Path) -> dict[str, Any]:
    experiment = load_yaml(experiment_path) or {}
    catalog = load_yaml(catalog_path) or {}
    sources = {entry.get("id"): entry for entry in catalog.get("sources", [])}
    method = experiment.get("method") or {}

    selected = []
    for source_id in experiment.get("sources", []):
        entry = sources.get(source_id)
        if entry is None:
            selected.append({"id": source_id, "problem": "Not in the source catalogue."})
        else:
            selected.append(check_catalog_entry(entry, catalog_path.parent))

    report = {
        "prepared_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "experiment_id": experiment.get("experiment_id"),
        "synthetic": bool((experiment.get("x_lab") or {}).get("synthetic")),
        "missing_experiment_fields": [k for k in EXPERIMENT_FIELDS if k not in experiment],
        "question": experiment.get("question"),
        "area": experiment.get("area"),
        "dates": experiment.get("dates"),
        "expected_output": experiment.get("expected_output"),
        "method_status": method.get("status", "pending"),
        "sources": selected,
        "submitted": False,
        "next_steps": [
            "Agree the method with the sprint team; this lab does not choose one.",
            "Fill every unconfirmed catalogue field from the publisher, not by guessing.",
            "Run `msl check` on any manifest; mangrove data may have no accepted contract yet.",
        ],
    }
    if report["method_status"] != "agreed":
        report["next_steps"].insert(0, "Method is pending: no analysis result can be produced.")
    out = outputs_dir / "experiments" / str(report["experiment_id"] or "unnamed")
    out.mkdir(parents=True, exist_ok=True)
    (out / "prepare.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["written_to"] = str(out / "prepare.json")
    return report

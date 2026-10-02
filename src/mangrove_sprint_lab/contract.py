"""Local manifest checks before anything is sent, plus the mangrove contract gaps.

Ported from GRP `core/contribution_rules.py` (ADPC, commit 14e4993, 2 October 2026; no licence
file in that repository, reused with the owner's permission). The required fields mirror what
the platform's own gate returned on 28 September 2026 and the runbook read on 2 October 2026.
They are a snapshot: the platform's gate has the last word, and its reply is shown verbatim.

Mangrove note: the published contribution kinds were designed for the risk and food-security
packs. A mangrove extent or carbon raster, or a mangrove polygon layer, does not fit them without
changing what the data means. `mangrove_gaps` names that instead of forcing a fit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

KINDS = ("vector", "raster", "table", "document", "weights")

REQUIRED: dict[str, tuple[str, ...]] = {
    "vector": ("layer", "url", "title", "description", "source", "license", "vintage"),
    "raster": (
        "layer", "url", "title", "description", "source", "license", "vintage", "legend",
        "declared",
    ),
    "table": (
        "dataset", "title", "description", "source", "validation", "license", "vintage",
        "cadence", "columns", "units",
    ),
    "document": ("pack", "url", "source", "title", "pub_date", "temporal", "validation"),
    "weights": ("hazard", "weights", "rationale"),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "vector": ("countries", "name_field", "usage_notes"),
    "raster": ("usage_notes",),
    "table": ("csv_text", "url", "as_of_field", "usage_notes", "pack"),
    "document": ("usage_notes", "doc_type", "event", "countries", "crops", "filename"),
    "weights": (),
}
# The field the platform knows the contribution by.
NAME_FIELD = {
    "vector": "layer", "raster": "layer", "table": "dataset", "document": "title",
    "weights": "hazard",
}
# Lab-only keys: kept locally for provenance and gating, stripped before sending.
LOCAL_KEYS = ("x_lab",)

VALIDATION = {
    "multi-agency-consensus", "peer-reviewed", "single-agency", "official-statistic",
    "unvalidated",
}
CADENCE = {"monthly", "daily", "annual", "irregular"}
TEMPORAL = {"forecast", "retrospective"}
PACKS = {"risk", "food-security"}
RASTER_PREFIXES = ("hazard_", "risk_", "vulnerability_", "population_")
SNAKE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
# Platform gate, 30 Sep 2026: "layer must be snake_case: lowercase letters, digits,
# underscores, 3-40 chars".
LAYER_NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?$")
DRIVE_FILE = re.compile(r"^/file/d/([A-Za-z0-9_-]{10,})")
CONTACT_FIELD = re.compile(
    r"(^|_|\b)(tel|telephone|phone|mobile|fax|e[-_]?mail|contact|line_?id)(\b|_|$)",
    re.IGNORECASE,
)
MANGROVE_WORDS = re.compile(r"mangrove|blue[_ ]?carbon|carbon[_ ]?stock|agb|canopy", re.I)


@dataclass
class Checked:
    kind: str | None
    manifest: dict[str, Any]
    problems: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def sendable(self) -> bool:
        return not self.problems and not self.gaps

    def wire_manifest(self) -> dict[str, Any]:
        """What actually goes to the platform: `kind` at the top, lab-only keys removed."""

        return {"kind": self.kind, **self.manifest}


def drive_download_url(url: str) -> tuple[str, str | None]:
    """A Google Drive share link in the direct-download form the platform can fetch."""

    text = (url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in {"drive.google.com", "docs.google.com"}:
        return text, None
    if "/folders/" in parsed.path:
        return text, "That is a Google Drive folder. Link the file itself ('Anyone with the link')."
    match = DRIVE_FILE.match(parsed.path) or re.match(
        r"^/(?:[a-z]+/)?d/([A-Za-z0-9_-]{10,})", parsed.path
    )
    file_id = match.group(1) if match else (parse_qs(parsed.query).get("id") or [None])[0]
    if not file_id:
        return text, "Could not find the file ID in that Google Drive link."
    return f"https://drive.google.com/uc?export=download&id={file_id}", None


def _as_mapping(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def mangrove_gaps(kind: str, manifest: dict[str, Any], lab: dict[str, Any]) -> list[str]:
    """Where a mangrove dataset meets no published contract. Each gap blocks sending."""

    gaps: list[str] = []
    about_mangroves = is_about_mangroves(manifest, lab)
    geometry = str(lab.get("geometry", "")).lower()
    if kind == "vector" and geometry and geometry != "point":
        gaps.append(
            f"The vector contract accepts Point features only; this dataset is {geometry}. "
            "Mangrove extent polygons have no published contribution kind. Ask SIG."
        )
    if kind == "raster" and about_mangroves:
        gaps.append(
            "The raster contract expects hazard_/risk_/vulnerability_ class maps (1-5) or a "
            "population_ count grid. A mangrove extent or carbon raster is neither; renaming or "
            "reclassifying it to fit would change its meaning. Ask SIG for a mangrove contract."
        )
    return gaps


def is_about_mangroves(manifest: dict[str, Any], lab: dict[str, Any]) -> bool:
    text = " ".join(str(manifest.get(key, "")) for key in ("layer", "title", "description"))
    return bool(MANGROVE_WORDS.search(text)) or lab.get("theme") == "mangrove"


def check_manifest(document: dict[str, Any]) -> Checked:
    """Clean the manifest and name every problem visible before sending it."""

    kind = document.get("kind")
    lab = document.get("x_lab") if isinstance(document.get("x_lab"), dict) else {}
    if kind not in KINDS:
        return Checked(None, {}, {"kind": f"Top-level kind must be one of: {', '.join(KINDS)}."})
    allowed = set(REQUIRED[kind]) | set(OPTIONAL[kind])
    cleaned: dict[str, Any] = {}
    checked = Checked(kind, cleaned)
    for key, value in document.items():
        if key == "kind" or key in LOCAL_KEYS:
            continue
        if key not in allowed:
            checked.notes.append(f"{key!r} is not a known {kind} field and will not be sent.")
            continue
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None, [], {}):
            continue
        cleaned[key] = value
    problems = checked.problems

    for key in REQUIRED[kind]:
        if key not in cleaned:
            problems[key] = "Required. If genuinely unknown, say so (e.g. license: unstated)."
    if kind == "table" and "csv_text" not in cleaned and "url" not in cleaned:
        problems["csv_text"] = "Paste the CSV or give a link to it."

    if "url" in cleaned:
        url, problem = drive_download_url(str(cleaned["url"]))
        if problem:
            problems["url"] = problem
        elif urlparse(url).scheme != "https":
            problems["url"] = "Use an https direct-download link the platform can fetch."
        elif "REPLACE" in url or (urlparse(url).hostname or "").endswith((".invalid", ".example")):
            problems["url"] = "Replace the placeholder with a real direct-download link."
        else:
            if url != cleaned["url"]:
                checked.notes.append("The Google Drive link was changed to its download form.")
            cleaned["url"] = url

    name_key = NAME_FIELD[kind]
    if kind in {"vector", "raster", "table"} and name_key in cleaned:
        name = str(cleaned[name_key])
        if not SNAKE.fullmatch(name):
            problems[name_key] = "Lower-case letters, digits and underscores; start with a letter."
        elif name_key == "layer" and not LAYER_NAME.fullmatch(name):
            problems[name_key] = f"The platform accepts 3 to 40 characters; this has {len(name)}."
        elif kind == "raster" and not name.startswith(RASTER_PREFIXES):
            problems[name_key] = "Start with hazard_, risk_, vulnerability_ or population_."

    for key in ("vintage", "pub_date"):
        if key in cleaned and not YEAR_MONTH.fullmatch(str(cleaned[key])):
            problems[key] = "Write the date as YYYY-MM (or YYYY-MM-DD), quoted in YAML."
    if "validation" in cleaned and cleaned["validation"] not in VALIDATION:
        problems["validation"] = f"One of: {', '.join(sorted(VALIDATION))}."
    if "cadence" in cleaned and cleaned["cadence"] not in CADENCE:
        problems["cadence"] = f"One of: {', '.join(sorted(CADENCE))}."
    if "temporal" in cleaned and cleaned["temporal"] not in TEMPORAL:
        problems["temporal"] = "forecast or retrospective."
    if "pack" in cleaned and cleaned["pack"] not in PACKS:
        problems["pack"] = f"One of the advertised packs: {', '.join(sorted(PACKS))}."
    if "usage_notes" in cleaned and len(str(cleaned["usage_notes"])) > 500:
        problems["usage_notes"] = "At most 500 characters."
    for key in ("countries", "crops"):
        if key in cleaned and isinstance(cleaned[key], str):
            cleaned[key] = [part.strip() for part in cleaned[key].split(",") if part.strip()]

    if kind == "raster" and str(cleaned.get("layer", "")).startswith("population_"):
        problems.pop("legend", None)
    for key in ("legend", "declared", "columns"):
        if key in cleaned:
            mapping = _as_mapping(cleaned[key])
            if mapping is None:
                problems[key] = "Give this as a mapping, for example {1: Very low}."
            else:
                cleaned[key] = mapping
    if kind == "raster" and isinstance(cleaned.get("declared"), dict):
        if any(key not in cleaned["declared"] for key in ("dtype", "valid_min", "valid_max")):
            problems["declared"] = "Needs dtype, valid_min and valid_max (and nodata if any)."

    if kind == "weights":
        weights = _as_mapping(cleaned.get("weights"))
        if weights is None and "weights" in cleaned:
            problems["weights"] = "Give the weights as layer: number pairs."
        elif weights is not None:
            try:
                numbers = {str(k): float(v) for k, v in weights.items()}
            except (TypeError, ValueError):
                problems["weights"] = "Every weight must be a number."
            else:
                if any(value < 0 for value in numbers.values()):
                    problems["weights"] = "Weights cannot be negative."
                elif abs(sum(numbers.values()) - 1.0) > 0.001:
                    total = sum(numbers.values())
                    problems["weights"] = f"The weights add up to {total:.3f}, not 1."
                elif any(name.startswith("population_") for name in numbers):
                    problems["weights"] = "A population count grid cannot be weighted."
                cleaned["weights"] = numbers

    checked.gaps.extend(mangrove_gaps(kind, cleaned, lab))
    if is_about_mangroves(cleaned, lab):
        checked.notes.append(
            "No mangrove pack is advertised (seen: risk, food-security). An accepted layer is "
            "stored and citable, but no mangrove analysis uses it until such a pack exists."
        )
    return checked


def load_manifest(path: Path) -> dict[str, Any]:
    """A manifest file: YAML or JSON with `kind` at the top level."""

    import yaml

    text = path.read_text(encoding="utf-8")
    document = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not a manifest mapping")
    return document


@dataclass
class FileCheck:
    path: str
    checked: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)


def check_geojson(path: Path) -> FileCheck:
    """Structure, coordinate order/range and contact fields. CRS beyond lon/lat is unchecked."""

    result = FileCheck(str(path))
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        result.problems.append(f"Not readable GeoJSON ({type(error).__name__}).")
        return result
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        result.problems.append("Not a GeoJSON FeatureCollection.")
        return result
    features = document.get("features") or []
    geometry_types: set[str] = set()
    properties: set[str] = set()
    bad_coordinates = 0

    def walk(coords: Any) -> None:
        nonlocal bad_coordinates
        if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
            if len(coords) < 2 or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
                bad_coordinates += 1
        elif isinstance(coords, list):
            for item in coords:
                walk(item)

    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        geometry_types.add(str(geometry.get("type")))
        walk(geometry.get("coordinates"))
        properties.update(((feature or {}).get("properties") or {}).keys())
    result.facts = {
        "features": len(features),
        "geometry_types": sorted(geometry_types),
        "properties": sorted(properties),
        "synthetic": bool((document.get("x_lab") or {}).get("synthetic")),
    }
    result.checked += ["FeatureCollection structure", "lon/lat coordinate range", "contact fields"]
    result.unchecked += [
        "declared CRS beyond lon/lat range", "geometry validity (self-intersection)",
        "attribute meaning and units", "agreement with the source's own totals",
    ]
    if not features:
        result.problems.append("No features.")
    if bad_coordinates:
        result.problems.append(f"{bad_coordinates} positions are outside lon/lat range.")
    blocked = sorted(name for name in properties if CONTACT_FIELD.search(name))
    if blocked:
        result.problems.append(f"Contact-like fields must not be shared: {', '.join(blocked)}.")
    return result


def check_local_file(path: Path) -> FileCheck:
    """The format checks this lab actually implements. Others are reported as unchecked."""

    if not path.is_file():
        result = FileCheck(str(path))
        result.problems.append("File not found.")
        return result
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        return check_geojson(path)
    result = FileCheck(str(path), facts={"bytes": path.stat().st_size})
    if suffix in {".tif", ".tiff"}:
        head = path.read_bytes()[:4]
        if head not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            result.problems.append("Not a TIFF file (bad header).")
        result.checked.append("TIFF header")
        result.unchecked += [
            "CRS (the platform requires EPSG:4326)", "dtype, nodata and value range",
            "resolution and extent", "legend/classes",
        ]
        result.facts["note"] = "Install GDAL/rasterio later for real raster checks."
    else:
        result.unchecked.append(f"No checks implemented for {suffix or 'this'} files.")
    return result

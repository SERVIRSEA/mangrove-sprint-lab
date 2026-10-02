from __future__ import annotations

import json
from pathlib import Path

import pytest

from mangrove_sprint_lab.config import ConfigError, load_environment
from mangrove_sprint_lab.contract import check_geojson, check_manifest, drive_download_url
from mangrove_sprint_lab.redact import redact, redact_text, redact_url
from mangrove_sprint_lab.traces import ModelUsage

BASE = {
    "kind": "vector", "layer": "plots_test_ab", "url": "https://example.org/a.geojson",
    "title": "t", "description": "d", "source": "s", "license": "CC0-1.0", "vintage": "2026-10",
}


def test_missing_fields_are_named_not_filled():
    checked = check_manifest({"kind": "vector", "layer": "plots_test_ab"})
    assert {"url", "title", "source", "license", "vintage"} <= set(checked.problems)
    assert "license" not in checked.manifest


def test_unknown_kind_is_refused():
    assert "kind" in check_manifest({"kind": "polygon"}).problems


def test_layer_longer_than_forty_characters_is_refused():
    checked = check_manifest({**BASE, "layer": "a" * 41})
    assert "40" in checked.problems["layer"]


def test_mangrove_polygons_are_a_contract_gap():
    checked = check_manifest({**BASE, "x_lab": {"geometry": "polygon", "theme": "mangrove"}})
    assert checked.gaps and "Point features only" in checked.gaps[0]
    assert not checked.sendable


def test_mangrove_raster_is_a_gap_and_not_renamed():
    raster = {
        **BASE, "kind": "raster", "layer": "mangrove_extent", "legend": {1: "mangrove"},
        "declared": {"dtype": "uint8", "valid_min": 0, "valid_max": 1},
    }
    checked = check_manifest(raster)
    assert any("mangrove" in gap for gap in checked.gaps)
    assert checked.manifest["layer"] == "mangrove_extent"


def test_placeholder_url_and_initials_are_refused():
    checked = check_manifest(
        {**BASE, "layer": "plots_test_YOURINITIALS", "url": "https://REPLACE-ME/x.geojson"}
    )
    assert {"layer", "url"} <= set(checked.problems)


def test_weights_must_sum_to_one():
    checked = check_manifest(
        {"kind": "weights", "hazard": "flood", "weights": {"a": 0.5, "b": 0.4}, "rationale": "r"}
    )
    assert "1" in checked.problems["weights"]


def test_lab_keys_never_go_on_the_wire():
    checked = check_manifest({**BASE, "x_lab": {"synthetic": True}})
    assert "x_lab" not in checked.wire_manifest()
    assert checked.wire_manifest()["kind"] == "vector"


def test_drive_share_link_becomes_download_link():
    url, problem = drive_download_url("https://drive.google.com/file/d/1AbCdEfGhIjK/view")
    assert problem is None
    assert url == "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjK"
    assert drive_download_url("https://drive.google.com/drive/folders/1AbCdEfGhIjK")[1]


def test_geojson_check_reports_checked_unchecked_and_contact_fields(tmp_path: Path):
    path = tmp_path / "p.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "a", "phone": "1"},
         "geometry": {"type": "Point", "coordinates": [100.5, 13.7]}},
        {"type": "Feature", "properties": {},
         "geometry": {"type": "Point", "coordinates": [13.7, 200.0]}},
    ]}), encoding="utf-8")
    result = check_geojson(path)
    assert result.checked and result.unchecked
    assert any("phone" in problem for problem in result.problems)
    assert any("outside lon/lat" in problem for problem in result.problems)


def test_signed_url_secrets_are_masked_but_source_kept():
    url = "https://bucket.s3.amazonaws.com/a.tif?X-Amz-Signature=abc123&X-Amz-Expires=60&v=2"
    masked = redact_url(url)
    assert "abc123" not in masked and "bucket.s3.amazonaws.com/a.tif" in masked and "v=2" in masked


def test_bearer_jwt_and_secret_keys_are_masked():
    text = "Authorization: Bearer abcdefghijklmnop and eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl"
    masked = redact_text(text)
    assert "abcdefghijklmnop" not in masked and "eyJzdWIiOi" not in masked
    assert redact({"refresh_token": "r" * 20, "ok": 1}) == {"refresh_token": "***", "ok": 1}


def test_unknown_model_usage_is_not_zero():
    usage = ModelUsage(status="unavailable", provider="x")
    assert usage.cost_usd is None and usage.input_tokens is None
    with pytest.raises(ValueError):
        ModelUsage(status="free")


def test_insecure_platform_url_is_refused():
    with pytest.raises(ConfigError):
        load_environment({"MSL_PLATFORM_URL": "http://servirplatform.sig-gis.com"}, dotenv=None)
    with pytest.raises(ConfigError):
        load_environment({"MSL_TRANSPORT": "stdio"}, dotenv=None)

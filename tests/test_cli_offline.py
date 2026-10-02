from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mangrove_sprint_lab.application.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def in_repo(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    for key in [key for key in os.environ if key.startswith("MSL_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MSL_TRANSPORT", "offline")
    monkeypatch.setenv("MSL_OUTPUTS_DIR", str(tmp_path / "out"))
    return tmp_path


def test_demo_runs_offline_without_credentials(in_repo, capsys):
    assert main(["demo"]) == 0
    captured = capsys.readouterr()
    assert "SYNTHETIC DEMO" in captured.err
    assert '"submitted": false' in captured.out


def test_offline_submit_refuses_and_exits_non_zero(in_repo, capsys):
    code = main([
        "submit", "data/examples/manifests/synthetic_plots_points.yml", "--confirm", "sig-hosted"
    ])
    assert code == 1
    assert "Not sent" in json.loads(capsys.readouterr().out)["error"]


def test_every_sample_manifest_is_blocked_until_edited(in_repo, capsys):
    for manifest in sorted((ROOT / "data/examples/manifests").glob("*.yml")):
        assert main(["check", str(manifest)]) == 1
        capsys.readouterr()


def test_prepare_marks_method_pending_and_nothing_submitted(in_repo, capsys):
    assert main(["prepare"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["method_status"] == "pending"
    assert report["submitted"] is False
    assert all(not source["missing_fields"] for source in report["sources"])


def test_local_operations_are_traced(in_repo, capsys):
    assert main(["demo"]) == 0
    capsys.readouterr()
    assert main(["traces", "-n", "20"]) == 0
    operations = {trace["operation"] for trace in json.loads(capsys.readouterr().out)}
    assert {"prepare", "preview"} <= operations

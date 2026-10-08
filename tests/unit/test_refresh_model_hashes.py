"""Unit tests for the maintainer script that pins model hashes and sizes.

The Hub is not contacted: `fetch_pinned_fields` is replaced, so what these
cover is how the script formats sizes and writes or checks models.json.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "refresh_model_hashes.py"


def load_script():
    """Import the script by path - its name is a command, not an identifier."""
    spec = importlib.util.spec_from_file_location("refresh_model_hashes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refresh = load_script()

FETCHED = {
    "files": {"model.bin": "sha256:" + "a" * 64},
    "repo_size": 78206636,
    "repo_size_human": "78.21 MB",
}


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (33695573, "33.70 MB"),
        (486215389, "486.22 MB"),
        (1621440951, "1.62 GB"),
        (6178178615, "6.18 GB"),
    ],
)
def test_sizes_are_decimal_with_two_decimals(size, expected):
    assert refresh.human_size(size) == expected


@pytest.fixture
def models_json(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    entry = {"repo_id": "aTrain-core/test", "revision": "abc", "files": {}, "repo_size": 1}
    path.write_text(json.dumps({"tiny": entry}))
    monkeypatch.setattr(refresh, "MODELS_JSON", path)
    monkeypatch.setattr(refresh, "fetch_pinned_fields", lambda repo_id, revision: FETCHED)
    return path


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["refresh_model_hashes.py", *args])
    return refresh.main()


def test_refresh_writes_hashes_and_sizes(models_json, monkeypatch):
    assert run(monkeypatch) == 0
    entry = json.loads(models_json.read_text())["tiny"]
    assert entry["files"] == FETCHED["files"]
    assert entry["repo_size"] == FETCHED["repo_size"]
    assert entry["repo_size_human"] == FETCHED["repo_size_human"]
    assert list(entry)[:2] == ["repo_id", "revision"], "existing keys keep their order"


def test_non_ascii_text_is_written_as_is(models_json, monkeypatch):
    data = json.loads(models_json.read_text())
    data["tiny"]["info"] = "Norwegian Bokmål"
    models_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    run(monkeypatch)
    assert "Bokmål" in models_json.read_text(encoding="utf-8")


def test_check_reports_size_drift(models_json, monkeypatch, capsys):
    data = json.loads(models_json.read_text())
    data["tiny"].update(files=FETCHED["files"], repo_size_human=FETCHED["repo_size_human"])
    models_json.write_text(json.dumps(data))

    assert run(monkeypatch, "--check") == 1
    out = capsys.readouterr().out
    assert "DRIFT tiny" in out
    assert "repo_size" in out


def test_check_passes_when_everything_matches(models_json, monkeypatch):
    data = json.loads(models_json.read_text())
    data["tiny"].update(FETCHED)
    models_json.write_text(json.dumps(data))

    assert run(monkeypatch, "--check") == 0

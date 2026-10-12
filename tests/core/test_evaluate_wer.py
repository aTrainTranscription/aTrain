"""Tests for scripts/evaluate_wer.py that need no model and no network.

They sit in tests/core rather than tests/unit because they need jiwer, which
only the engine jobs install.
"""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_wer.py"


def load_script():
    """Import the script by path - scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("evaluate_wer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate_wer = load_script()
MODELS = {"good": {}, "bad": {}, "english": {"languages": ["en"]}}


def test_english_contractions_count_as_equal():
    assert evaluate_wer.score("it's fine", "it is fine", english=True) == 0


def test_english_rules_only_apply_to_english():
    assert evaluate_wer.wer_transform(english=True)("geht's") == [["geht", "is"]]
    assert evaluate_wer.wer_transform(english=False)("geht's") == [["gehts"]]


def test_a_byte_order_mark_does_not_count(fake_atrain, tmp_path, capsys):
    (tmp_path / "ref.txt").write_text("﻿the cat sat on the mat", encoding="utf-8")
    evaluate_wer.main([*fake_atrain, "--models", "good"])
    assert " 0.00%" in capsys.readouterr().out


def test_transcript_text_drops_the_header(tmp_path):
    (tmp_path / "transcription.txt").write_text(
        "Transcription for x\n\nfirst line\nsecond line", encoding="utf-8"
    )
    assert evaluate_wer.transcript_text(tmp_path) == "first line\nsecond line"


def test_transcribe_runs_atrain_in_the_cache_and_cleans_up(tmp_path, monkeypatch):
    """The real subprocess path, with aTrain itself replaced by a stub."""
    cache = tmp_path / "cache"
    cache.mkdir()
    audio = tmp_path / "my talk.mp3"
    audio.write_bytes(b"")
    calls = []

    def fake_run(command, env, **kwargs):
        calls.append((command, env))
        out = cache / "transcriptions" / "x"
        out.mkdir(parents=True)
        (out / "transcription.txt").write_text("header\n\nhello world", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(evaluate_wer.subprocess, "run", fake_run)
    text = evaluate_wer.transcribe(audio, "tiny", "en", "cpu", cache)

    assert text == "hello world"
    [(command, env)] = calls
    assert env["ATRAIN_USER_DIR"] == str(cache), "must never use the user's real folder"
    assert command[command.index("--model") + 1] == "tiny"
    assert " " not in Path(command[command.index("transcribe") + 1]).name
    assert os.listdir(cache / "transcriptions") == []
    assert not (cache / "wer-eval.mp3").exists()


@pytest.fixture
def fake_atrain(tmp_path, monkeypatch):
    """Replace model loading and transcription; each model 'says' a fixed text."""
    said = {"good": "the cat sat on the mat", "bad": "the dog sat"}
    monkeypatch.setattr(evaluate_wer, "load_model_config_file", lambda: MODELS)
    monkeypatch.setattr(
        evaluate_wer, "atrain_core", lambda args, data_dir: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        evaluate_wer, "transcribe", lambda audio, model, language, device, data_dir: said[model]
    )
    reference = tmp_path / "ref.txt"
    reference.write_text("the cat sat on the mat", encoding="utf-8")
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"")
    return [str(audio), str(reference), "--cache-dir", str(tmp_path / "cache")]


def test_prints_a_row_per_model(fake_atrain, capsys):
    assert evaluate_wer.main([*fake_atrain, "--models", "good", "bad"]) == 0
    out = capsys.readouterr().out
    assert "good" in out and "0.00%" in out
    assert "bad" in out


def test_max_wer_sets_the_exit_code(fake_atrain):
    assert evaluate_wer.main([*fake_atrain, "--models", "good", "--max-wer", "0.1"]) == 0
    assert evaluate_wer.main([*fake_atrain, "--models", "good", "bad", "--max-wer", "0.1"]) == 1


def test_language_restricted_model_needs_a_matching_language(fake_atrain):
    with pytest.raises(SystemExit, match="only supports en; pass --language en"):
        evaluate_wer.main([*fake_atrain, "--models", "english"])


def test_unknown_model_is_reported_before_anything_runs(fake_atrain):
    with pytest.raises(SystemExit, match=r"missing is not in models\.json"):
        evaluate_wer.main([*fake_atrain, "--models", "missing"])


def test_missing_files_are_reported_before_anything_runs(fake_atrain, tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        evaluate_wer.main([str(tmp_path / "nope.mp3"), *fake_atrain[1:], "--models", "good"])


def test_runs_must_be_positive(fake_atrain):
    with pytest.raises(SystemExit):
        evaluate_wer.main([*fake_atrain, "--runs", "0"])

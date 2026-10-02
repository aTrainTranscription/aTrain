"""Tests for aTrain_core.engine with fake models (no model download, no GPU)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from aTrain_core import engine, runner
from aTrain_core.backends import crisper_transformers
from aTrain_core.backends.common import SRT_MAX_DURATION, group_word_segments
from aTrain_core.outputs import finalize
from aTrain_core.settings import ComputeType, Device, ModelKey, validate_job_settings


def key(model: str) -> ModelKey:
    return ModelKey(model, Device.CPU, ComputeType.INT8, 4)


@pytest.mark.parametrize(
    ("model", "backend"),
    [("tiny", "faster-whisper"), ("crisperwhisper-v2-large", "crisper-transformers")],
)
def test_load_transcriber_picks_backend_from_models_json(monkeypatch, model, backend):
    calls = []

    class Fake:
        def __init__(self, key, model_path):
            calls.append((key, model_path))

    monkeypatch.setitem(engine.TRANSCRIBERS, backend, Fake)
    transcriber = engine.load_transcriber(key(model), Path("/models/x"))
    assert isinstance(transcriber, Fake)
    assert calls == [(key(model), Path("/models/x"))]


def test_load_transcriber_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unsupported transcription backend"):
        engine.load_transcriber(key("speaker-detection"), Path("/models/x"))


def test_validate_job_settings_rejects_crisper_auto_detect():
    validate_job_settings("crisperwhisper-v2-large", "de", Device.CPU)
    with pytest.raises(ValueError):
        validate_job_settings("crisperwhisper-v2-large", "auto-detect", Device.CPU)


def word(text, start, end):
    return {"word": text, "start": start, "end": end, "probability": 0.9}


def test_faster_whisper_transcriber_keeps_segments_without_word_timestamps():
    segments = [
        SimpleNamespace(
            start=0.0,
            end=1.0,
            text=" Hello world.",
            words=[word(" Hello", 0.0, 0.4), word(" world.", 0.5, 1.0)],
        ),
        SimpleNamespace(start=1.5, end=2.0, text=" Yes.", words=[]),
        SimpleNamespace(start=2.5, end=3.0, text=" ", words=[]),
    ]
    calls = []
    fake_model = SimpleNamespace(
        transcribe=lambda **kwargs: (
            calls.append(kwargs) or (iter(segments), SimpleNamespace(duration=3.0))
        )
    )
    transcriber = object.__new__(engine.FasterWhisperTranscriber)
    transcriber._model, transcriber._model_type = fake_model, "regular"
    log, progress = [], {}

    transcript = transcriber.transcribe(
        "audio",
        language="auto-detect",
        initial_prompt=None,
        temperature=None,
        progress=progress,
        log=log.append,
    )

    assert [s["text"] for s in transcript["segments"]] == ["Hello", "world.", "Yes."]
    assert calls[0]["language"] is None and calls[0]["condition_on_previous_text"] is True
    assert progress == {"task": "Transcribe", "current": 3.0, "total": 3.0}
    assert "Segment without word timestamps kept as one word: 1.5s" in log


def test_sent_transcription_progress_never_exceeds_the_total():
    sent = []
    channel = SimpleNamespace(send=sent.append)
    progress = runner.EventProgress(channel, "a", interval=0)  # send every change
    segments = [SimpleNamespace(end=30.7), SimpleNamespace(end=61.4)]

    engine.transcription_with_progress_bar(segments, SimpleNamespace(duration=197.5), progress)

    assert sent and all(e.current <= e.total for e in sent)
    assert (sent[-1].current, sent[-1].total) == (61.4, 197.5)


def test_crisper_transcribe_with_model_logs_ignored_settings():
    result = SimpleNamespace(words=[word("Hi", 0.0, 0.3)], text="Hi")
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: result)
    log, progress = [], {}

    transcript = crisper_transformers.transcribe_with_model(
        model,
        "audio",
        language="de",
        initial_prompt="x",
        temperature=0.2,
        progress=progress,
        log=log.append,
    )

    assert [s["text"] for s in transcript["segments"]] == ["Hi"]
    assert progress == {"task": "Transcribe", "current": 1, "total": 1}
    assert len(log) == 2
    with pytest.raises(ValueError):
        crisper_transformers.transcribe_with_model(
            model,
            "audio",
            language="auto-detect",
            initial_prompt=None,
            temperature=None,
            progress={},
            log=log.append,
        )


@pytest.mark.parametrize(
    ("backend", "join_raw"), [("faster-whisper", True), ("crisper-transformers", False)]
)
def test_finalize_groups_cues_and_subtitles(backend, join_raw):
    words = [
        (" Das", 0.0, 0.3, "A"),
        (" ist", 0.4, 0.6, "A"),
        (" gut.", 0.7, 1.0, "A"),
        (" Ja.", 1.2, 1.4, "B"),
    ]
    segments = [
        {
            "start": s,
            "end": e,
            "text": t.strip(),
            "speaker": sp,
            "words": [{"word": t, "start": s, "end": e}],
        }
        for t, s, e, sp in words
    ]

    cues, subtitles = finalize({"segments": segments}, backend)

    assert cues == {"segments": group_word_segments(segments, join_raw)}
    assert subtitles == {
        "segments": group_word_segments(segments, join_raw, max_duration=SRT_MAX_DURATION)
    }
    assert [c["speaker"] for c in cues["segments"]] == ["A", "B"]


def test_decode_reports_invalid_file(tmp_path):
    log = []
    with pytest.raises(Exception, match="Check file & path"):
        engine.decode(tmp_path / "missing.mp3", log.append)
    assert log[0].startswith("File or path invalid")

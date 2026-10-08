"""Tests for aTrain_core.engine with fake models (no model download, no GPU)."""

from types import SimpleNamespace

import pytest
from aTrain_core import engine, runner
from aTrain_core.settings import Device, validate_job_settings


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

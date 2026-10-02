"""In-process tests for aTrain_core.runner with fake models and a fake channel."""

from pathlib import Path

import numpy as np
import pytest
from aTrain_core import outputs, runner
from aTrain_core.backends.common import words_to_segments
from aTrain_core.jobs import Step
from tests.unit.test_jobs import make_spec

TIMESTAMP = "2026-09-30 14-05-12"


class FakeChannel:
    """Records the events a child sends."""

    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)

    def of(self, kind):
        return [e for e in self.events if isinstance(e, kind)]


class FakeTranscriber:
    backend = "faster-whisper"

    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], set(fail_on)

    def transcribe(self, audio, *, language, initial_prompt, temperature, progress, log):
        self.calls.append(language)
        if len(self.calls) in self.fail_on:
            raise RuntimeError("model error")
        progress["task"] = "Transcribe"
        progress["current"], progress["total"] = 1.0, 1.0
        words = [
            {"word": " Hello", "start": 0.0, "end": 0.4},
            {"word": " there.", "start": 0.5, "end": 1.0},
        ]
        return {"segments": words_to_segments(words)}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Archive in tmp, fake decode and fake diarize (every word gets SPEAKER_00)."""
    monkeypatch.setattr(outputs, "TRANSCRIPT_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(runner, "decode", lambda source, log: (np.zeros(16000, np.float32), 1))
    diarized = []

    def fake_diarize(pipeline, audio, transcript, *, speaker_count, progress, log):
        diarized.append(transcript)
        for segment in transcript["segments"]:
            segment["speaker"] = "SPEAKER_00"
        return transcript

    monkeypatch.setattr(runner, "diarize", fake_diarize)
    return tmp_path, diarized


def make_job(tmp_path, job_id, **overrides) -> runner.PhaseJob:
    source = tmp_path / f"{job_id}.mp3"
    if not source.exists():
        source.write_bytes(b"audio " + job_id.encode())
    spec = make_spec(
        id=job_id, source=source, display_name=f"{job_id}.mp3", export_dir=None, **overrides
    )
    return runner.PhaseJob(spec, TIMESTAMP, tmp_path / "work" / job_id)


def test_phase1_loads_the_model_of_the_job(env):
    tmp_path, _ = env
    loads, transcriber = [], FakeTranscriber()
    job = make_job(tmp_path, "a", speaker_detection=False)
    channel = FakeChannel()

    runner.run_phase1(job, channel, lambda key: loads.append(key) or transcriber)

    assert loads == [job.spec.model_key]
    assert [e.job_id for e in channel.of(runner.JobDone)] == ["a"]


def test_phase1_writes_outputs_for_jobs_without_speaker_detection(env):
    tmp_path, _ = env
    job = make_job(tmp_path, "a", speaker_detection=False)
    channel = FakeChannel()

    runner.run_phase1(job, channel, lambda key: FakeTranscriber())

    kinds = [type(e) for e in channel.events if not isinstance(e, runner.JobProgress)]
    assert kinds == [runner.JobFileId, runner.JobDone]
    file_id = channel.of(runner.JobFileId)[0].file_id
    directory = tmp_path / "transcriptions" / file_id
    assert (
        (directory / "transcription.txt")
        .read_text(encoding="utf-8")
        .strip()
        .endswith("Hello there.")
    )
    assert "Transcription successful" in (directory / "log.txt").read_text(encoding="utf-8")
    assert channel.of(runner.JobProgress)[-1].current == 1.0


def test_failing_job_sends_job_failed(env):
    tmp_path, _ = env
    job = make_job(tmp_path, "a", speaker_detection=False)
    channel = FakeChannel()

    runner.run_phase1(job, channel, lambda key: FakeTranscriber(fail_on={1}))

    failed = channel.of(runner.JobFailed)
    assert [(f.job_id, f.step, f.error) for f in failed] == [
        ("a", Step.TRANSCRIPTION, "model error")
    ]
    assert channel.of(runner.JobDone) == []


def test_speaker_detection_goes_through_both_phases(env):
    tmp_path, diarized = env
    job = make_job(tmp_path, "a")
    phase1 = FakeChannel()
    runner.run_phase1(job, phase1, lambda key: FakeTranscriber())
    assert [
        type(e) for e in phase1.events if isinstance(e, runner.JobTranscribed | runner.JobDone)
    ] == [runner.JobTranscribed]
    assert (job.work_dir / runner.RAW_CHECKPOINT).is_file()

    phase2 = FakeChannel()
    runner.run_phase2(job, phase2, lambda device: "pipeline")

    assert len(diarized) == 1 and (job.work_dir / runner.DIARIZED_CHECKPOINT).is_file()
    file_id = phase2.of(runner.JobFileId)[0].file_id
    text = (tmp_path / "transcriptions" / file_id / "transcription.txt").read_text(encoding="utf-8")
    assert "SPEAKER_00" in text


def test_valid_checkpoints_are_reused(env):
    tmp_path, diarized = env
    job = make_job(tmp_path, "a")
    transcript = {"segments": words_to_segments([{"word": " Saved.", "start": 0.0, "end": 0.5}])}
    for name in (runner.RAW_CHECKPOINT, runner.DIARIZED_CHECKPOINT):
        outputs.write_checkpoint(
            job.work_dir / name, transcript=transcript, audio_duration=3, source=job.spec.source
        )
    transcriber = FakeTranscriber()

    runner.run_phase1(job, FakeChannel(), lambda key: transcriber)
    phase2 = FakeChannel()
    runner.run_phase2(job, phase2, lambda device: "pipeline")

    assert transcriber.calls == [] and diarized == []
    assert phase2.of(runner.JobDone)[0].audio_duration == 3


def test_output_error_keeps_checkpoints(env, monkeypatch):
    tmp_path, _ = env

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(runner, "write_final_outputs", broken)
    job = make_job(tmp_path, "a")
    runner.run_phase1(job, FakeChannel(), lambda key: FakeTranscriber())
    channel = FakeChannel()
    runner.run_phase2(job, channel, lambda device: "pipeline")

    assert [(f.step, f.error) for f in channel.of(runner.JobFailed)] == [(Step.OUTPUT, "disk full")]
    assert (job.work_dir / runner.RAW_CHECKPOINT).is_file()
    assert (job.work_dir / runner.DIARIZED_CHECKPOINT).is_file()


def test_phase2_with_changed_source_fails_without_diarizing(env):
    tmp_path, diarized = env
    job = make_job(tmp_path, "a")
    runner.run_phase1(job, FakeChannel(), lambda key: FakeTranscriber())
    Path(job.spec.source).write_bytes(b"another recording")

    channel = FakeChannel()
    runner.run_phase2(job, channel, lambda device: "pipeline")

    failed = channel.of(runner.JobFailed)[0]
    assert failed.step == Step.DIARIZATION and "recording changed" in failed.error
    assert diarized == []


def test_source_replaced_during_transcription_is_not_diarized(env):
    tmp_path, diarized = env
    job = make_job(tmp_path, "a")

    class ReplacingTranscriber(FakeTranscriber):
        def transcribe(self, audio, **kwargs):
            Path(job.spec.source).write_bytes(b"another recording")
            return super().transcribe(audio, **kwargs)

    runner.run_phase1(job, FakeChannel(), lambda key: ReplacingTranscriber())
    channel = FakeChannel()
    runner.run_phase2(job, channel, lambda device: "pipeline")

    assert "recording changed" in channel.of(runner.JobFailed)[0].error
    assert diarized == []


@pytest.mark.parametrize("phase", [1, 2])
def test_source_changed_while_decoding_fails_the_job(env, monkeypatch, phase):
    tmp_path, diarized = env
    job = make_job(tmp_path, "a")
    if phase == 2:
        runner.run_phase1(job, FakeChannel(), lambda key: FakeTranscriber())

    def decode_while_replaced(source, log):
        Path(source).write_bytes(b"another recording")
        return np.zeros(16000, np.float32), 1

    monkeypatch.setattr(runner, "decode", decode_while_replaced)
    transcriber, channel = FakeTranscriber(), FakeChannel()
    if phase == 1:
        runner.run_phase1(job, channel, lambda key: transcriber)
    else:
        runner.run_phase2(job, channel, lambda device: "pipeline")

    failed = channel.of(runner.JobFailed)[0]
    assert "changed while it was read" in failed.error
    assert transcriber.calls == [] and diarized == []


def test_event_progress_throttles_and_flushes_the_last_value():
    sent, now = [], [0.0]
    channel = FakeChannel()
    channel.send = sent.append
    progress = runner.EventProgress(channel, "a", interval=0.2, clock=lambda: now[0])

    progress["task"] = "Transcribe"  # a new task is sent at once
    for i in range(1, 6):
        now[0] = i * 0.05
        progress["current"] = i
    progress.flush()

    assert [(e.task, e.current) for e in sent] == [
        ("Transcribe", 0),
        ("Transcribe", 4),
        ("Transcribe", 5),
    ]
    progress.flush()  # nothing new
    assert len(sent) == 3

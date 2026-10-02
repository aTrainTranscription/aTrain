"""Unit tests for aTrain_core.jobs: JobSpec / JobState JSON, transitions, resume_status."""

from pathlib import Path

import pytest
from aTrain_core.jobs import (
    ALLOWED,
    InvalidTransitionError,
    JobSpec,
    JobState,
    JobStatus,
    Step,
    check_transition,
    resume_status,
)
from aTrain_core.settings import ComputeType, Device, ModelKey


def make_spec(**overrides) -> JobSpec:
    values = {
        "id": "3f2c9b0e8d7a4c1e9f00b2a1c3d4e5f6",
        "source": Path("/home/ana/Interviews/interview_03.m4a"),
        "display_name": "interview_03.m4a",
        "model": "large-v3-turbo",
        "language": "de",
        "device": Device.GPU,
        "compute_type": ComputeType.FLOAT16,
        "cpu_threads": 8,
        "temperature": None,
        "initial_prompt": None,
        "speaker_detection": True,
        "speaker_count": 2,
        "export_dir": Path("/home/ana/Interviews/transcriptions"),
    }
    values.update(overrides)
    return JobSpec(**values)


def test_spec_json_round_trip():
    spec = make_spec()
    data = spec.to_json()
    assert data["device"] == "gpu" and data["source"] == str(spec.source)
    assert JobSpec.from_json(data) == spec
    assert JobSpec.from_json(make_spec(export_dir=None).to_json()).export_dir is None


def test_state_json_round_trip_drops_memory_only_fields():
    state = JobState(
        status=JobStatus.FAILED,
        file_id="2609301405-intervi",
        failed_step=Step.OUTPUT,
        error="disk full",
        warnings=["Copy failed"],
        progress=0.5,
        cancelling=True,
    )
    data = state.to_json()
    assert "progress" not in data and "cancelling" not in data
    restored = JobState.from_json(data)
    assert restored.failed_step == Step.OUTPUT and restored.warnings == ["Copy failed"]
    assert restored.progress == 0.0 and restored.cancelling is False


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (JobSpec, {**make_spec().to_json(), "speaker_names": []}),
        (JobState, {**JobState().to_json(), "surprise": 1}),
        (JobState, {**JobState().to_json(), "progress": 0.5}),
    ],
)
def test_unknown_keys_raise(cls, data):
    with pytest.raises(ValueError, match="Unknown"):
        cls.from_json(data)


def test_model_key_groups_gpu_jobs_regardless_of_cpu_threads():
    assert make_spec(cpu_threads=4).model_key == make_spec(cpu_threads=8).model_key
    assert make_spec().model_key == ModelKey("large-v3-turbo", Device.GPU, ComputeType.FLOAT16, 0)
    cpu = {"device": Device.CPU, "compute_type": ComputeType.INT8}
    assert make_spec(cpu_threads=4, **cpu).model_key != make_spec(cpu_threads=8, **cpu).model_key


def test_to_settings_copies_every_setting():
    spec = make_spec(temperature=0.2, initial_prompt="Interview")
    settings = spec.to_settings(file_id="f", timestamp="t", progress={})
    assert settings.file == spec.source and settings.file_name == spec.display_name
    assert (settings.file_id, settings.timestamp) == ("f", "t")
    assert (settings.temperature, settings.initial_prompt) == (0.2, "Interview")
    assert (settings.speaker_count, settings.cpu_threads) == (2, 8)


@pytest.mark.parametrize("speaker_detection", [True, False])
@pytest.mark.parametrize("old", list(JobStatus))
@pytest.mark.parametrize("new", list(JobStatus))
def test_transition_matrix(old, new, speaker_detection):
    spec = make_spec(speaker_detection=speaker_detection)
    speaker_only = {JobStatus.TRANSCRIBED, JobStatus.DIARIZING}
    allowed = new in ALLOWED[old] and (speaker_detection or new not in speaker_only)
    if allowed:
        check_transition(spec, old, new)
    else:
        with pytest.raises(InvalidTransitionError):
            check_transition(spec, old, new)


def test_failed_and_cancelled_reachable_from_every_active_status():
    for status in (
        JobStatus.QUEUED,
        JobStatus.TRANSCRIBING,
        JobStatus.TRANSCRIBED,
        JobStatus.DIARIZING,
    ):
        assert {JobStatus.FAILED, JobStatus.CANCELLED} <= ALLOWED[status]


def test_resume_status():
    with_speakers, without = make_spec(), make_spec(speaker_detection=False)
    assert resume_status(with_speakers, raw_checkpoint_valid=True) == JobStatus.TRANSCRIBED
    assert resume_status(with_speakers, raw_checkpoint_valid=False) == JobStatus.QUEUED
    assert resume_status(without, raw_checkpoint_valid=True) == JobStatus.QUEUED
    # every result is reachable from every status resume_status is used on
    for status in (
        JobStatus.TRANSCRIBING,
        JobStatus.DIARIZING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ):
        check_transition(with_speakers, status, JobStatus.QUEUED)
        check_transition(with_speakers, status, JobStatus.TRANSCRIBED)

"""Unit tests for aTrain_core.jobs: JobSpec / JobState JSON."""

from pathlib import Path

import pytest
from aTrain_core.jobs import JobSpec, JobState, JobStatus, Step
from aTrain_core.settings import ComputeType, Device


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


def test_state_json_round_trip():
    state = JobState(
        status=JobStatus.FAILED,
        file_id="2609301405-intervi",
        failed_step=Step.OUTPUT,
        error="disk full",
        warnings=["Copy failed"],
    )
    restored = JobState.from_json(state.to_json())
    assert restored == state and restored.failed_step == Step.OUTPUT


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (JobSpec, {**make_spec().to_json(), "speaker_names": []}),
        (JobState, {**JobState().to_json(), "surprise": 1}),
        (JobState, {**JobState().to_json(), "progress": 0.5}),
    ],
)
def test_unknown_keys_raise(cls, data):
    with pytest.raises(TypeError):
        cls.from_json(data)


def test_to_settings_copies_every_setting():
    spec = make_spec(temperature=0.2, initial_prompt="Interview")
    settings = spec.to_settings(file_id="f", timestamp="t", progress={})
    assert settings.file == spec.source and settings.file_name == spec.display_name
    assert (settings.file_id, settings.timestamp) == ("f", "t")
    assert (settings.temperature, settings.initial_prompt) == (0.2, "Interview")
    assert (settings.speaker_count, settings.cpu_threads) == (2, 8)

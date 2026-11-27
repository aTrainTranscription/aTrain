"""Settings is sent to a spawned child process for GPU work, so it must stay picklable."""

import io
import pickle
from pathlib import Path

import pytest
from aTrain_core.settings import ComputeType, Device, Settings


def make_settings(file) -> Settings:
    return Settings(
        file=file,
        file_id="id",
        file_name="a.mp3",
        model="tiny",
        language="en",
        speaker_detection=False,
        speaker_count=None,
        device=Device.GPU,
        compute_type=ComputeType.INT8,
        timestamp="t",
        temperature=None,
    )


def test_file_is_stored_as_path():
    assert make_settings("a.mp3").file == Path("a.mp3")


def test_settings_survive_pickling():
    settings = make_settings(Path("a.mp3"))
    assert pickle.loads(pickle.dumps(settings)) == settings  # noqa: S301  own data


def test_open_file_object_is_rejected():
    with pytest.raises(TypeError):
        make_settings(io.BytesIO(b"audio"))

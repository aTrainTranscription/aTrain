"""GPU work runs in a child process so the OS frees all GPU memory when it exits.

No GPU needed: run_in_process is tested with stdlib targets, the GPU routing with a fake.
"""

import json
import os

import numpy as np
import pytest
from aTrain_core import transcribe
from aTrain_core.settings import ComputeType, Device, Settings


def test_run_in_process_runs_target_in_another_process():
    assert transcribe.run_in_process(os.getpid) != os.getpid()


def test_run_in_process_returns_result():
    assert transcribe.run_in_process(json.loads, s="[1, 2]") == [1, 2]


def test_run_in_process_reraises_error():
    with pytest.raises(json.JSONDecodeError):
        transcribe.run_in_process(json.loads, s="{")


def test_run_in_process_reports_crashed_child():
    with pytest.raises(RuntimeError, match="ended unexpectedly"):
        transcribe.run_in_process(os.abort)


def settings(device: Device) -> Settings:
    return Settings(
        file="a.mp3",
        file_id="id",
        file_name="a.mp3",
        model="tiny",
        language="en",
        speaker_detection=True,
        speaker_count=None,
        device=device,
        compute_type=ComputeType.INT8,
        timestamp="t",
        temperature=None,
    )


@pytest.mark.parametrize(("device", "isolated"), [(Device.GPU, True), (Device.CPU, False)])
def test_speaker_detection_on_gpu_runs_in_child_process(monkeypatch, device, isolated):
    calls = []
    monkeypatch.setattr(transcribe, "write_logfile", lambda *a, **k: None)
    monkeypatch.setattr(
        transcribe, "run_in_process", lambda target, **kw: calls.append("process") or "child"
    )
    monkeypatch.setattr(
        transcribe, "detect_speakers", lambda *a, **kw: calls.append("inline") or "inline"
    )

    transcribe.run_speaker_detection(settings(device), 1, np.zeros(16000), {"segments": []})

    assert calls == (["process"] if isolated else ["inline"])

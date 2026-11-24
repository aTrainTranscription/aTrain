"""GPU work runs in a child process so the OS frees all GPU memory when it exits.

No GPU needed: run_in_process is tested with stdlib targets, the GPU routing with a fake.
"""

import json
import multiprocessing
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


def _read_marker():
    return getattr(transcribe, "_parent_only_marker", None)


@pytest.fixture
def default_start_method_fork():
    """Make fork the global default, as it is on Linux (until Python 3.14)."""
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork is not available on this platform")
    previous = multiprocessing.get_start_method()
    multiprocessing.set_start_method("fork", force=True)
    yield
    multiprocessing.set_start_method(previous, force=True)


@pytest.mark.usefixtures("default_start_method_fork")
def test_run_in_process_starts_a_clean_interpreter(monkeypatch):
    # A forked child inherits the parent's state, an initialised CUDA context included,
    # and then cannot initialise CUDA itself. A spawned child starts clean.
    monkeypatch.setattr(transcribe, "_parent_only_marker", True, raising=False)
    assert transcribe.run_in_process(_read_marker) is None


def _init_cuda_in_child() -> bool:
    import torch

    torch.zeros(1, device="cuda")
    return True


def test_gpu_child_initialises_cuda_after_parent_checked_device():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("needs a CUDA GPU")
    from aTrain_core.settings import check_device

    check_device(Device.GPU)  # what the CLI does before transcribing
    assert transcribe.run_in_process(_init_cuda_in_child)


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

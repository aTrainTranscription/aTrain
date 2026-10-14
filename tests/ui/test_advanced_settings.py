"""Interaction tests for the Advanced Settings page.

Covers the five settings of `advanced_settings_body`: GPU, compute-type,
cpu-threads, temperature, initial-prompt. Sister to
`tests/ui/test_settings_components.py` (the always-visible transcribe-page
settings); the GPU switch is the one input here that depends on host
hardware (lazy `from torch import cuda`), so we mock `cuda.is_available`
for deterministic behaviour across CPU-only and GPU runners.

The settings live on their own page (`/advanced`). The transcribe page seeds
the same defaults (`seed_defaults`), so a job can be added without opening
that page first.
"""

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
import pytest
from aTrain_core.cli import DEFAULT_CPU_THREADS
from aTrain_core.settings import ComputeType
from nicegui import app, ui
from nicegui.testing import User


@pytest.fixture
def no_cuda(monkeypatch):
    """Force input_gpu to render as if CUDA is unavailable."""
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)


@pytest.fixture
def cuda_available(monkeypatch):
    """Force input_gpu to render as if CUDA is available."""
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)


async def _open_dialog(user: User):
    """Render the Advanced Settings page."""
    await user.open("/advanced")
    await user.should_see("Advanced Settings", retries=100)


def _last(user: User, marker: str):
    """Return the element for a marker."""
    return list(user.find(marker=marker).elements)[-1]


# --- input_gpu: CUDA gating + storage seeding -----------------------------


async def test_input_gpu_storage_seeded_false_when_no_cuda(user: User, no_cuda):
    # seed_defaults on the transcribe page writes storage["GPU"] = False
    # when CUDA is unavailable, without opening the Advanced Settings page.
    await user.open("/")
    await user.should_see("Advanced Settings", retries=100)
    assert app.storage.general["GPU"] is False


async def test_input_gpu_switch_defaults_to_true_with_cuda(user: User, cuda_available):
    await _open_dialog(user)
    await user.should_see("GPU acceleration", retries=100)
    switch = _last(user, "switch_gpu")
    assert switch.value is True


async def test_input_gpu_toggle_writes_storage(user: User, cuda_available):
    await _open_dialog(user)
    await user.should_see("GPU acceleration", retries=100)
    _last(user, "switch_gpu").set_value(False)
    assert app.storage.general["GPU"] is False
    _last(user, "switch_gpu").set_value(True)
    assert app.storage.general["GPU"] is True


# --- input_compute_type: default + GPU-off restriction -------------------


async def test_input_compute_type_defaults_to_int8(user: User, cuda_available):
    # The select is seeded from storage["compute_type"] or ComputeType.INT8.
    # On first render storage is empty → INT8.
    await _open_dialog(user)
    await user.should_see("Compute Type", retries=100)
    assert app.storage.general["compute_type"] == ComputeType.INT8.value


async def test_input_compute_type_options_restricted_when_gpu_off(user: User, no_cuda):
    # input_gpu sets storage["GPU"]=False → set_compute_options() collapses
    # the select options to [INT8] only.
    await _open_dialog(user)
    await user.should_see("Compute Type", retries=100)
    select = _last(user, "select_compute")
    assert list(select.options) == [ComputeType.INT8.value]


# --- input_cpu_threads: default + reset button ---------------------------


async def test_input_cpu_threads_default_and_reset(user: User, cuda_available):
    await _open_dialog(user)
    await user.should_see("CPU Threads", retries=100)
    number = _last(user, "number_cpu_threads")
    assert number.value == DEFAULT_CPU_THREADS
    number.set_value(8)
    assert number.value == 8
    user.find(marker="button_reset_cpu_threads").click()
    assert number.value == DEFAULT_CPU_THREADS


# --- input_temperature: default + reset button --------------------------


async def test_input_temperature_default_none_and_reset(user: User, cuda_available):
    await _open_dialog(user)
    await user.should_see("Temperature", retries=100)
    number = _last(user, "number_temperature")
    assert number.value is None  # placeholder "auto"
    number.set_value(0.5)
    assert app.storage.general["temperature_override"] == 0.5
    user.find(marker="button_reset_temperature").click()
    assert number.value is None
    assert app.storage.general["temperature_override"] is None


# --- input_initial_prompt: textarea binds to storage --------------------


async def test_input_initial_prompt_binds_to_storage(user: User, cuda_available):
    await _open_dialog(user)
    await user.should_see("Initial Prompt", retries=100)
    textarea = _last(user, "textarea_initial_prompt")
    textarea.set_value("hello world")
    assert app.storage.general["initial_prompt"] == "hello world"


async def test_transcribe_page_seeds_the_defaults(user: User, cuda_available):
    # A job can be added without opening the Advanced Settings page first.
    await user.open("/")
    await user.should_see(kind=ui.button, content="Transcribe", retries=100)
    assert app.storage.general["GPU"] is True
    assert app.storage.general["compute_type"] == ComputeType.INT8.value
    assert app.storage.general["cpu_threads"] == DEFAULT_CPU_THREADS

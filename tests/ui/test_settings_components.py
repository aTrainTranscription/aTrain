"""Interaction tests for the always-visible transcribe-page settings.

Covers the three settings always visible on `/`: speakers, language,
model. Mounts the real transcribe page and
drives each through the NiceGUI in-process `user` fixture, asserting
their user-visible state transitions (storage binding, default-value
selection, select-option changes).

Out of scope here — the advanced settings (GPU, compute-type, cpu-threads,
temperature, initial-prompt) have their own page and tests
(`test_advanced_settings.py`).

The transcribe page is the natural place to exercise these components —
each one is mounted there exactly as a user sees it (rather than in a
synthetic test page), which keeps the test environment honest.
"""

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
import pytest
from aTrain.components.settings import model as model_component
from nicegui import app
from nicegui.testing import User

# app.storage.general is cleared between tests by NiceGUI's own
# `nicegui_reset_globals` fixture (autouse via the `user` fixture chain),
# which calls app.reset() → self.storage.clear() and binding.reset().
# No explicit per-test storage cleanup needed.


@pytest.fixture
def known_models(monkeypatch):
    """Make input_model see a predictable set of models (`tiny`, `base`)
    regardless of what's downloaded on the host."""
    monkeypatch.setattr(model_component, "read_transcription_models", lambda: ["tiny", "base"])


# --- speakers: one select for detection and count ---------------------------
# (custom count keyboard interaction: tests/e2e_browser/test_transcribe_interactions.py)


async def test_speakers_select_writes_storage(user: User):
    await user.open("/")
    await user.should_see("Speakers", retries=100)
    select = next(iter(user.find(marker="select_speakers").elements))
    select.set_value("auto")
    assert app.storage.general["speaker_detection"] is True
    assert app.storage.general["speaker_count"] is None
    select.set_value(3)
    assert app.storage.general["speaker_detection"] is True
    assert app.storage.general["speaker_count"] == 3
    select.set_value("off")
    assert app.storage.general["speaker_detection"] is False
    assert app.storage.general["speaker_count"] is None


# --- language: select falls back to first available language for a model ---


async def test_language_select_picks_default_for_known_model(user: User, known_models):
    # With `tiny` as the first available model, input_model writes
    # model="tiny" into storage; input_language then seeds language to the
    # first key in languages.json for that model, which is "auto-detect"
    # for the multilingual tiny model.
    await user.open("/")
    await user.should_see("Language", retries=100)
    assert app.storage.general["model"] == "tiny"
    assert app.storage.general["language"] == "auto-detect"


# --- language: opening the select and picking a different option ----------


async def test_language_select_change_writes_storage(user: User, known_models):
    await user.open("/")
    await user.should_see("Language", retries=100)
    # input_language tags its select with `.mark("select_language")`, which
    # lets us drive it directly: first click opens the popup, second click
    # on the option label picks it.
    user.find(marker="select_language").click()
    user.find("english").click()
    assert app.storage.general["language"] == "en"


# --- model: default seeded on first render --------------------------------


async def test_model_default_seeded_on_first_render(user: User, known_models):
    await user.open("/")
    await user.should_see("Model", retries=100)
    # `tiny` is the first entry → input_model picks it as the default.
    assert app.storage.general["model"] == "tiny"


# --- model: changing the model select also refreshes the language list ----


async def test_model_select_change_writes_storage_and_refreshes_language(user: User, known_models):
    await user.open("/")
    await user.should_see("Model", retries=100)
    assert app.storage.general["model"] == "tiny"
    # Pick the model select by its mark and drive its value. `set_value`
    # triggers the on_value_change handler which then calls
    # update_language_options.
    model_select = next(iter(user.find(marker="select_model").elements))
    model_select.set_value("base")
    assert app.storage.general["model"] == "base"
    # `base` is also multilingual → update_language_options seeds the first
    # key for the new model, which is "auto-detect".
    assert app.storage.general["language"] == "auto-detect"

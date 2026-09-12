"""Interaction tests for the always-visible transcribe-page settings.

Covers the four settings always visible on `/`: speaker-detection,
speaker-count, language, model. Mounts the real transcribe page and
drives each through the NiceGUI in-process `user` fixture, asserting
their user-visible state transitions (storage binding, default-value
selection, select-option changes, visibility binding).

Out of scope here — `advanced_settings` (GPU, compute-type, cpu-threads,
temperature, initial-prompt) sits behind a dialog and lazy-imports
`torch.cuda`; it is a separate follow-up.

The transcribe page is the natural place to exercise these components —
each one is mounted there exactly as a user sees it (rather than in a
synthetic test page), which keeps the test environment honest.
"""

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
import pytest
from aTrain.components.settings import model as model_component
from nicegui import app, ui
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


def _find_ancestor_column(user: User, label_text: str) -> ui.column:
    """Locate the `ui.column` whose subtree contains a label with the given text.

    Walks the client's full element registry — `user.find(ui.column)` skips
    elements with `visible=False`, which is exactly the case we need to assert
    for the speaker-count visibility binding.
    """
    for element in user.client.elements.values():
        if getattr(element, "text", None) == label_text and element.parent_slot:
            parent = element.parent_slot.parent
            while parent is not None:
                if isinstance(parent, ui.column):
                    return parent
                parent = parent.parent_slot.parent if parent.parent_slot else None
    raise AssertionError(f"no ui.column ancestor found for label {label_text!r}")


# --- speaker_detection: switch toggles, value writes into storage ----------


async def test_speaker_detection_toggle_writes_storage(user: User):
    await user.open("/")
    await user.should_see("Speaker Detection", retries=100)
    # Select the speaker-detection switch by its mark — `find(ui.switch)`
    # alone would also match the GPU switch inside advanced_settings if
    # that dialog ever defaults open.
    user.find(marker="switch_speaker_detection").click()
    assert app.storage.general["speaker_detection"] is True
    user.find(marker="switch_speaker_detection").click()
    assert app.storage.general["speaker_detection"] is False


# --- speaker_count: column visibility binds to speaker_detection -----------


async def test_speaker_count_column_visibility_follows_detection(user: User):
    # The column wrapping "Number of Speakers" binds its `.visible` attribute
    # to app.storage.general["speaker_detection"]. should_see / should_not_see
    # only check element existence (the DOM keeps hidden elements), so we
    # assert the `.visible` attribute on the column directly.
    await user.open("/")
    await user.should_see("Speaker Detection", retries=100)
    column = _find_ancestor_column(user, "Number of Speakers")
    assert column.visible is False  # detection off / missing → hidden
    user.find(marker="switch_speaker_detection").click()  # enable detection
    assert column.visible is True
    user.find(marker="switch_speaker_detection").click()  # disable again
    assert column.visible is False


# --- language: select falls back to first available language for a model ---


async def test_language_select_picks_default_for_known_model(user: User, known_models):
    # With `tiny` as the first available model, input_model writes
    # model="tiny" into storage; input_language then seeds language to the
    # first key in languages.json for that model, which is "auto-detect"
    # for the multilingual tiny model.
    await user.open("/")
    await user.should_see("Select Language", retries=100)
    assert app.storage.general["model"] == "tiny"
    assert app.storage.general["language"] == "auto-detect"


# --- language: opening the select and picking a different option ----------


async def test_language_select_change_writes_storage(user: User, known_models):
    await user.open("/")
    await user.should_see("Select Language", retries=100)
    # input_language tags its select with `.mark("select_language")`, which
    # lets us drive it directly: first click opens the popup, second click
    # on the option label picks it.
    user.find(marker="select_language").click()
    user.find("english").click()
    assert app.storage.general["language"] == "en"


# --- model: default seeded on first render --------------------------------


async def test_model_default_seeded_on_first_render(user: User, known_models):
    await user.open("/")
    await user.should_see("Select Model", retries=100)
    # `tiny` is the first entry → input_model picks it as the default.
    assert app.storage.general["model"] == "tiny"


# --- model: changing the model select also refreshes the language list ----


async def test_model_select_change_writes_storage_and_refreshes_language(user: User, known_models):
    await user.open("/")
    await user.should_see("Select Model", retries=100)
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

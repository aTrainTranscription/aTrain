"""Real-browser interaction smokes for the transcribe page.

Sister to `test_pages_render.py` (pure render/presence). These drive
actual clicks and assert reactive JS-side state - visibility toggles
and dialog open/close - that the in-process NiceGUI User fixture
can't observe (it inspects Python-side element state, not the DOM
Quasar produces).
"""

from playwright.sync_api import Page, expect


def test_speaker_detection_toggle_reveals_speaker_count(atrain_server: str, page: Page) -> None:
    """Speaker-count column is bound to the `speaker_detection` flag
    (speaker_count.py::input_speaker_count → bind_visibility). Toggling
    the switch must show/hide the column in the actual DOM."""
    page.goto(atrain_server)
    speaker_count = page.get_by_text("Number of Speakers")
    expect(speaker_count).to_be_hidden()

    # Two "Speaker Detection" strings render (section header + switch label).
    # The switch label is the second occurrence; .last targets it.
    switch_label = page.get_by_text("Speaker Detection").last
    switch_label.click()
    expect(speaker_count).to_be_visible()

    switch_label.click()
    expect(speaker_count).to_be_hidden()


def test_advanced_settings_button_opens_dialog(atrain_server: str, page: Page) -> None:
    """The Advanced Settings dialog is embedded closed on the transcribe
    page and re-created on button click. `GPU acceleration` lives only
    inside the dialog, so its visibility is a clean proxy for open-state."""
    page.goto(atrain_server)
    gpu_label = page.get_by_text("GPU acceleration").last
    expect(gpu_label).to_be_hidden()

    page.get_by_role("button", name="Advanced Settings").click()
    expect(gpu_label).to_be_visible()

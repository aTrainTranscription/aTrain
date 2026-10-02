"""Real-browser interaction smokes for the transcribe page.

Sister to `test_pages_render.py` (pure render/presence). These drive
actual clicks and assert reactive JS-side state - visibility toggles
and page navigation - that the in-process NiceGUI User fixture
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


def test_sidebar_opens_advanced_settings(atrain_server: str, page: Page) -> None:
    """Advanced Settings is a sidebar page, no longer a dialog on the
    transcribe page. `GPU acceleration` only renders on that page."""
    page.goto(atrain_server)
    expect(page.get_by_text("GPU acceleration")).to_have_count(0)

    page.get_by_role("link", name="Advanced Settings").click()
    expect(page.get_by_text("GPU acceleration")).to_be_visible()

"""Real-browser interaction smokes for the transcribe page.

Sister to `test_pages_render.py` (pure render/presence). These drive
actual clicks and assert reactive JS-side state - visibility toggles
and page navigation - that the in-process NiceGUI User fixture
can't observe (it inspects Python-side element state, not the DOM
Quasar produces).
"""

from playwright.sync_api import Page, expect


def test_speakers_select_takes_a_custom_count(atrain_server: str, page: Page) -> None:
    """The "More" row below the Speakers options is a number input inside the select's
    menu (speakers.py::input_speakers). Typing in it and pressing Enter must reach the
    input, not the select's keyboard navigation."""
    page.goto(atrain_server)
    speakers = page.locator(".q-select").nth(2)  # Model, Language, Speakers
    expect(page.get_by_text("Speakers", exact=True)).to_be_visible(timeout=60_000)

    speakers.click()
    menu = page.locator(".q-menu")
    menu.get_by_text("2 speakers", exact=True).click()
    expect(speakers).to_contain_text("2 speakers")

    speakers.click()
    number = menu.locator("input[type=number]")
    number.fill("2")
    number.press("Enter")
    expect(menu.get_by_text("Enter a whole number from 3 to 99.")).to_be_visible()
    number.fill("12")
    number.press("Enter")
    expect(menu).to_be_hidden()
    expect(speakers).to_contain_text("12 speakers")


def test_sidebar_opens_advanced_settings(atrain_server: str, page: Page) -> None:
    """Advanced Settings is a sidebar page, no longer a dialog on the
    transcribe page. `GPU acceleration` only renders on that page."""
    page.goto(atrain_server)
    expect(page.get_by_text("GPU acceleration")).to_have_count(0)

    page.get_by_role("link", name="Advanced Settings").click()
    expect(page.get_by_text("GPU acceleration")).to_be_visible()

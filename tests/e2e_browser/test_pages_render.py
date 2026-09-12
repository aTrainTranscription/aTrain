"""Real-browser render smoke tests for the app's main pages.

Parallels tests/ui/test_pages_render.py (which drives NiceGUI's in-process
`User` fixture). These tests hit the actual JS / CSS / WebSocket path through
a real Chromium - they catch client-side rendering regressions and
browser-server contract issues the in-process fixture cannot see.

Scope of the initial PoC: render + presence smokes on the same subset of
pages the in-process suite covers. Interaction coverage (file-upload flow,
speaker-count binding, model selection) can be layered on later.
"""

from playwright.sync_api import Page, expect


def test_main_page_loads(atrain_server: str, page: Page) -> None:
    page.goto(atrain_server)
    # First visit: the splash shows while torch loads in the background, and
    # only then the page renders. A cold import can take well over the 5 s
    # expect default on a CI runner, so wait explicitly for the handover.
    expect(page.get_by_text("Starting Application")).to_be_visible()
    expect(page.get_by_text("Select File").first).to_be_visible(timeout=60_000)
    expect(page.get_by_text("Speaker Detection").first).to_be_visible()


def test_about_page_loads(atrain_server: str, page: Page) -> None:
    page.goto(f"{atrain_server}/about")
    expect(page.get_by_text("About aTrain").first).to_be_visible()


def test_faq_page_loads(atrain_server: str, page: Page) -> None:
    page.goto(f"{atrain_server}/faq")
    expect(page.get_by_text("Frequently Asked Questions").first).to_be_visible()


def test_archive_page_loads(atrain_server: str, page: Page) -> None:
    page.goto(f"{atrain_server}/archive")
    # Archive shows either an empty-state label or a table header, depending
    # on host state. Assert the page mounts by presence of the archive nav
    # marker instead of content-dependent text.
    expect(page.get_by_text("Archive").first).to_be_visible()


def test_models_page_loads(atrain_server: str, page: Page) -> None:
    page.goto(f"{atrain_server}/models")
    expect(page.get_by_text("Models").first).to_be_visible()

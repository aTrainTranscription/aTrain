"""The macOS native window picks files with pywebview's own file dialog.

The web page's file dialog does not open in pywebview's macOS window (#307). The drop
zone's "Browse" therefore goes through `pick_in_window`, not through the desktop portal
(Linux and Flatpak only). The test pretends to be macOS on any CI platform.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
import pytest
from aTrain.components.settings import file as file_component
from aTrain.utils.file_selection import FileSelection
from nicegui import app
from nicegui.testing import User

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"


@pytest.fixture
def macos_window(monkeypatch) -> Mock:
    """A native window on macOS whose file dialog returns the fixture."""
    window = Mock()  # stands in for NiceGUI's proxy of the native window
    window.create_file_dialog = AsyncMock(return_value=(str(FIXTURE),))
    monkeypatch.setattr(file_component, "FLATPAK", False)
    monkeypatch.setattr(file_component, "LINUX", False)
    monkeypatch.setattr(app.native, "main_window", window)
    return window


async def test_browse_opens_the_native_dialog_on_macos(macos_window, user: User, monkeypatch):
    made = []

    class Recorded(FileSelection):
        def __init__(self, *args):
            super().__init__(*args)
            made.append(self)

    monkeypatch.setattr(file_component, "FileSelection", Recorded)
    await user.open("/")
    await user.should_see(marker="add_to_queue", retries=200)
    selection = made[-1]
    assert selection.native and not selection.portal

    with user:
        await selection.browse_files()

    macos_window.create_file_dialog.assert_awaited_once()
    assert selection.paths == [FIXTURE]

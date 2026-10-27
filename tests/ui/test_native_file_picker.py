"""The macOS native window picks the file with pywebview's own file dialog.

The web page's file dialog (`<input type="file">` behind "Select File") does
not open in pywebview's macOS window (#307), the same reason Linux and Flatpak
use a native picker. The test pretends to be macOS on any CI platform.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import aTrain_core.globals
import aTrain_core.transcribe  # pre-import so the splash import is instant
import pytest
from aTrain.components.settings import file as file_component
from nicegui import app, ui
from nicegui.testing import User

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"


@pytest.fixture
def macos_window(monkeypatch) -> Mock:
    """A native window on macOS whose file dialog returns the fixture."""
    window = Mock()  # stands in for NiceGUI's proxy of the native window
    window.create_file_dialog = AsyncMock(return_value=(str(FIXTURE),))
    # The page module is imported fresh per test and reads the globals then;
    # the component module persists, so patch its copies too.
    for module in (aTrain_core.globals, file_component):
        monkeypatch.setattr(module, "FLATPAK", False)
        monkeypatch.setattr(module, "LINUX", False)
        monkeypatch.setattr(module, "MACOS", True, raising=False)
    monkeypatch.setattr(app.native, "main_window", window)
    return window


async def test_select_file_opens_the_native_dialog_on_macos(macos_window, user: User):
    await user.open("/")
    await user.should_see("Start", retries=100)

    user.find(kind=ui.button, content="Select File").click()

    await user.should_see(FIXTURE.name)
    macos_window.create_file_dialog.assert_awaited_once()

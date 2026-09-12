"""Render smoke tests for the non-transcribe pages.

Drives the in-process NiceGUI `user` fixture against `/about`, `/faq`,
`/archive`, and `/models`, asserting each page renders without crashing
and shows an expected anchor string. Complements
test_click_through.py::test_main_page_renders which covers `/`.

These are smokes, not interaction tests: they only verify the page mounts
and a stable label is visible. They catch the "page no longer renders" /
"import-time error in a page module" class of breakage without exercising
buttons or dialogs.
"""

from pathlib import Path

import aTrain_core.globals as core_globals
import pytest
from aTrain.utils import archive as archive_utils
from aTrain.utils import models as models_utils
from nicegui.testing import User


@pytest.fixture
def isolated_user_dir(tmp_path, monkeypatch):
    """Redirect the on-disk paths the pages touch into tmp_path.

    aTrain_core.globals computes TRANSCRIPT_DIR / MODELS_DIR at import time
    from ATRAIN_USER_DIR, so by the time a test runs they are already frozen
    Path objects. We patch the attributes directly on every module that
    rebound them via `from aTrain_core.globals import ...` — the names the
    page code actually reads.
    """
    transcript_dir = tmp_path / "transcriptions"
    models_dir = tmp_path / "models"
    for module, attr, value in [
        (core_globals, "TRANSCRIPT_DIR", transcript_dir),
        (core_globals, "MODELS_DIR", models_dir),
        (core_globals, "REQUIRED_MODELS_DIR", models_dir),
        (archive_utils, "TRANSCRIPT_DIR", transcript_dir),
        (models_utils, "MODELS_DIR", models_dir),
        (models_utils, "REQUIRED_MODELS_DIR", models_dir),
    ]:
        monkeypatch.setattr(module, attr, value)
    return tmp_path


async def test_about_page_renders(user: User):
    await user.open("/about")
    await user.should_see("About aTrain", retries=100)


async def test_faq_page_renders(user: User):
    await user.open("/faq")
    await user.should_see("Frequently Asked Questions", retries=100)


async def test_archive_page_renders_empty(isolated_user_dir: Path, user: User):
    # No transcriptions on disk → the page still renders header + actions.
    await user.open("/archive")
    await user.should_see("Archive", retries=100)
    await user.should_see("Show All")
    await user.should_see("Delete All")


async def test_models_page_renders(isolated_user_dir: Path, user: User):
    await user.open("/models")
    await user.should_see("Model Manager", retries=100)

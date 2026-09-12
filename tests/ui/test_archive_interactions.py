"""Interaction tests for the /archive page.

Drives the buttons on the archive page through the NiceGUI in-process
`user` fixture and asserts the resulting filesystem state (since the
click handlers call `delete_transcription` and `open_file_directory`
directly). The `show` action invokes `subprocess.run(["xdg-open", ...])`
which would actually try to open a file manager on CI, so the
underlying utility is monkeypatched to a recorder.
"""

import aTrain_core.globals as core_globals
import pytest
from aTrain.utils import archive as archive_utils
from nicegui.testing import User


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    """Redirect TRANSCRIPT_DIR to a tmp dir on every module that rebound it,
    so the page reads/writes inside the test sandbox."""
    root = tmp_path / "transcriptions"
    root.mkdir()
    for module in (core_globals, archive_utils):
        monkeypatch.setattr(module, "TRANSCRIPT_DIR", root)
    return root


def _seed(root, *names):
    """Create transcription subdirectories under root. No metadata file →
    read_metadata_from_dir_name fallback path."""
    for name in names:
        (root / name).mkdir()


@pytest.fixture
def show_recorder(monkeypatch):
    """Replace open_file_directory with a recorder so the test doesn't
    actually shell out to xdg-open / show-in-file-manager.

    Patched on the persistent utils module (the page module is re-imported
    fresh per test and copies the name at import time), so this fixture must
    be listed before `user` in the test signature."""
    calls = []
    monkeypatch.setattr(archive_utils, "open_file_directory", lambda file_id: calls.append(file_id))
    return calls


# --- list rendering --------------------------------------------------------


async def test_archive_empty_renders_headers(user: User, archive_root):
    await user.open("/archive")
    await user.should_see("Archive", retries=100)
    await user.should_see("Show All")
    await user.should_see("Delete All")
    # No transcriptions seeded → only the column-headers row is rendered.
    await user.should_not_see("delete")  # per-row delete button absent
    await user.should_not_see("open")


async def test_archive_lists_seeded_transcriptions(user: User, archive_root):
    # read_metadata_from_dir_name puts directory[20:] into "filename"; the
    # first 20 chars are the timestamp slot. Pick names long enough that the
    # filename portion is recognisable for the assertion.
    _seed(archive_root, "2024-01-01-10-00-00-recordingA", "2024-01-02-10-00-00-recordingB")
    await user.open("/archive")
    await user.should_see("Archive", retries=100)
    await user.should_see("recordingA")
    await user.should_see("recordingB")


# --- per-row delete (no dialog) -------------------------------------------


async def test_archive_row_delete_button_removes_directory(user: User, archive_root):
    # One seeded row → the page shows exactly one "delete" button, so
    # user.find("delete").click() unambiguously targets that row's handler.
    # The handler calls delete_transcription(file_id) + ui.navigate.reload();
    # reload is a no-op in the in-process user fixture, so we assert on the
    # filesystem instead of re-rendering.
    _seed(archive_root, "rec1")
    await user.open("/archive")
    await user.should_see("Archive", retries=100)
    user.find("delete").click()
    assert list(archive_root.iterdir()) == []


# --- show buttons (mocked open_file_directory) ----------------------------


async def test_archive_show_all_button_invokes_show_with_all(
    archive_root, show_recorder, user: User
):
    await user.open("/archive")
    await user.should_see("Show All", retries=100)
    user.find("Show All").click()
    assert show_recorder == ["all"]


async def test_archive_row_open_button_invokes_show_with_file_id(
    archive_root, show_recorder, user: User
):
    # One seeded row → exactly one per-row "open" button, so the find
    # unambiguously targets that row's handler. Symmetric to the show-all
    # test above — verifies the per-row click is wired to show(file_id).
    _seed(archive_root, "rec1")
    await user.open("/archive")
    await user.should_see("Archive", retries=100)
    user.find("open").click()
    assert show_recorder == ["rec1"]


# --- delete-all dialog ----------------------------------------------------


async def test_archive_delete_all_dialog_confirm_clears_directory(user: User, archive_root):
    _seed(archive_root, "rec1", "rec2", "rec3")
    await user.open("/archive")
    await user.should_see("Delete All", retries=100)
    user.find("Delete All").click()  # opens dialog_delete
    await user.should_see("Are you sure you want to delete all transcriptions?")
    user.find("Confirm").click()
    # delete("all") removed everything and recreated the empty root.
    assert archive_root.exists()
    assert list(archive_root.iterdir()) == []


async def test_archive_delete_all_dialog_cancel_keeps_transcriptions(user: User, archive_root):
    _seed(archive_root, "rec1", "rec2")
    await user.open("/archive")
    await user.should_see("Delete All", retries=100)
    user.find("Delete All").click()
    await user.should_see("Are you sure you want to delete all transcriptions?")
    user.find("Cancel").click()
    # Nothing was deleted.
    assert {p.name for p in archive_root.iterdir()} == {"rec1", "rec2"}

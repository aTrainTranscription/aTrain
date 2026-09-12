"""Unit tests for aTrain/utils/archive.py — the transcription-archive file handler.

Characterization tests: they pin the module's current behaviour as a
regression net. Torch- and NiceGUI-free, so they run in the lightweight
`unit` CI job (no app runtime).
"""

import pytest
from aTrain.utils import archive


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    """Point archive.TRANSCRIPT_DIR at an isolated temp dir.

    archive.py rebinds TRANSCRIPT_DIR into its own namespace via
    `from aTrain_core.globals import ...`, so we patch the name on
    `archive` (what the functions actually read), not on aTrain_core.globals.
    The directory is NOT created here — several functions create it on
    demand, and that behaviour is part of what these tests pin.
    """
    root = tmp_path / "transcriptions"
    monkeypatch.setattr(archive, "TRANSCRIPT_DIR", root)
    return root


# --- read_metadata_from_dir_name: pure string parsing, no IO ---------------

_LONG = "2024-01-01 12-00-00recording.mp3"  # > 20 chars


@pytest.mark.parametrize(
    ("directory", "expected_timestamp", "expected_filename"),
    [
        pytest.param(_LONG, _LONG[:20], _LONG[20:], id="long"),
        # At exactly 20 chars the timestamp is filled (len >= 20) but the
        # filename is not (len > 20 is False) — asymmetric boundary in the
        # current code, pinned here on purpose.
        pytest.param("x" * 20, "x" * 20, "-", id="exactly-20"),
        pytest.param("short", "-", "-", id="short"),
    ],
)
def test_metadata_from_dir_name(directory, expected_timestamp, expected_filename):
    meta = archive.read_metadata_from_dir_name(directory)
    assert meta["file_id"] == directory
    assert meta["timestamp"] == expected_timestamp
    assert meta["filename"] == expected_filename


# --- check_access ----------------------------------------------------------


def test_check_access_existing_dir(tmp_path):
    assert archive.check_access(str(tmp_path)) is True


def test_check_access_missing_path(tmp_path):
    assert archive.check_access(str(tmp_path / "nope")) is False


def test_check_access_readable_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hi")
    assert archive.check_access(str(f)) is True


# --- read_directories ------------------------------------------------------


def test_read_directories_creates_dir_when_missing(archive_root):
    # The dir does not exist yet; read_directories must create it and return [].
    assert not archive_root.exists()
    assert archive.read_directories() == []
    assert archive_root.is_dir()


def test_read_directories_sorted_reverse_dirs_only(archive_root):
    archive_root.mkdir()
    for name in ("a", "b", "c"):
        (archive_root / name).mkdir()
    (archive_root / "loose_file.txt").write_text("x")
    assert archive.read_directories() == ["c", "b", "a"]


# --- read_metadata_file ----------------------------------------------------


def test_read_metadata_file_injects_file_id(tmp_path):
    meta_path = tmp_path / "metadata.txt"
    meta_path.write_text("model: tiny\nlanguage: en\n")
    meta = archive.read_metadata_file(str(meta_path), "dir-123")
    assert meta["model"] == "tiny"
    assert meta["language"] == "en"
    assert meta["file_id"] == "dir-123"


# --- read_all_metadata -----------------------------------------------------


def test_read_all_metadata_uses_file_when_present(archive_root):
    d = archive_root / "rec1"
    d.mkdir(parents=True)
    (d / archive.METADATA_FILENAME).write_text("model: tiny\n")
    [meta] = archive.read_all_metadata(["rec1"])
    assert meta["model"] == "tiny"
    assert meta["file_id"] == "rec1"


def test_read_all_metadata_falls_back_to_dir_name(archive_root):
    (archive_root / "rec2").mkdir(parents=True)  # no metadata file
    [meta] = archive.read_all_metadata(["rec2"])
    assert meta["file_id"] == "rec2"
    assert meta["filename"] == "-"  # short dir name → dir-name fallback


# --- read_archive: the public orchestrator the GUI calls -------------------


def test_read_archive_merges_file_and_dirname_metadata(archive_root):
    # "bbb" has a metadata file, "aaa" does not. read_archive lists dirs
    # reverse-sorted (bbb before aaa) and merges both metadata sources.
    bbb = archive_root / "bbb"
    bbb.mkdir(parents=True)
    (bbb / archive.METADATA_FILENAME).write_text("model: tiny\n")
    (archive_root / "aaa").mkdir(parents=True)

    result = archive.read_archive()

    assert [m["file_id"] for m in result] == ["bbb", "aaa"]
    assert result[0]["model"] == "tiny"  # from the metadata file
    assert result[1]["filename"] == "-"  # dir-name fallback for "aaa"


# --- delete_transcription --------------------------------------------------


def test_delete_transcription_removes_dir(archive_root):
    d = archive_root / "rec3"
    d.mkdir(parents=True)
    archive.delete_transcription("rec3")
    assert not d.exists()
    assert archive_root.exists()


def test_delete_transcription_all_clears_and_recreates(archive_root):
    (archive_root / "rec4").mkdir(parents=True)
    archive.delete_transcription("all")
    assert archive_root.exists()
    assert list(archive_root.iterdir()) == []


# --- load_faqs: bundled resource access ------------------------------------


def test_load_faqs_returns_list_of_qa_entries():
    # Smoke test for importlib.resources.files("aTrain.static") resolving the
    # bundled faq.yaml — the kind of resource lookup a packaging change can
    # silently break.
    faqs = archive.load_faqs()
    assert isinstance(faqs, list)
    assert all("question" in entry and "answer" in entry for entry in faqs)

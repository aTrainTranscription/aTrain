"""Unit tests for aTrain_core.discovery."""

from aTrain_core import discovery


def make_files(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("audio")


def test_top_level_supported_files_only(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "load_formats", lambda: [".mp3", ".wav"])
    make_files(tmp_path, "b.wav", "a.mp3", "C.MP3", "notes.txt", ".hidden.mp3", "nested/d.mp3")

    files = discovery.discover_media_files(tmp_path)

    assert [path.name for path in files] == ["a.mp3", "b.wav", "C.MP3"]


def test_recursive_skips_hidden_and_export_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "load_formats", lambda: [".mp3"])
    make_files(
        tmp_path,
        "a.mp3",
        "Day 2/b.mp3",
        ".cache/c.mp3",
        "transcriptions/2609301405-a/d.mp3",
        "sub/transcriptions/e.mp3",
    )

    files = discovery.discover_media_files(tmp_path, recursive=True)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "a.mp3",
        "Day 2/b.mp3",
        "sub/transcriptions/e.mp3",
    ]

"""Unit tests for aTrain_core.discovery."""

from aTrain_core import discovery, settings


def make_files(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("audio")


def test_top_level_supported_files_only(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "load_formats", lambda: [".mp3", ".wav"])
    make_files(tmp_path, "b.wav", "a.mp3", "C.MP3", "notes.txt", ".hidden.mp3", "nested/d.mp3")

    files = discovery.discover_media_files(tmp_path)

    assert [path.name for path in files] == ["a.mp3", "b.wav", "C.MP3"]

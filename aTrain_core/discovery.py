from pathlib import Path

from aTrain_core.settings import allowed_extensions


def discover_media_files(folder: Path) -> list[Path]:
    """List the supported media files in a folder, sorted case-insensitively.
    Hidden files are skipped."""
    allowed = allowed_extensions()
    files = []
    for path in folder.iterdir():
        if path.name.startswith("."):
            continue
        if path.is_file() and path.suffix.lower() in allowed:
            files.append(path)
    return sorted(files, key=lambda path: path.name.lower())

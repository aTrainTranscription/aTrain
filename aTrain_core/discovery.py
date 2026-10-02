from pathlib import Path

from aTrain_core.settings import load_formats

EXPORT_DIRNAME = "transcriptions"


def discover_media_files(folder: Path, recursive: bool = False) -> list[Path]:
    """List the supported media files in a folder, sorted case-insensitively.
    Hidden files are skipped; with recursive=True also the export subfolder."""
    allowed_extensions = {extension.lower() for extension in load_formats()}
    candidates = folder.rglob("*") if recursive else folder.iterdir()
    files = []
    for path in candidates:
        parts = path.relative_to(folder).parts
        if any(part.startswith(".") for part in parts):
            continue
        if recursive and parts[0] == EXPORT_DIRNAME:
            continue
        if path.is_file() and path.suffix.lower() in allowed_extensions:
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(folder).as_posix().lower())

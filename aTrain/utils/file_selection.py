"""The files picked or dropped for the next jobs, behind the drop zone of the transcribe page."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from aTrain.utils import flatpak_portal
from aTrain_core.globals import FLATPAK
from aTrain_core.settings import load_formats
from nicegui import app, events, run, ui


class FileSelection:
    """The files for the next jobs, as paths: picked, a folder, dropped in the Linux window,
    or browser files, which the hidden uploader uploads into the queue's upload folder as
    soon as they are added. `native`: a desktop window, whose dialogs give paths
    (`portal`: through the desktop portal, in the Linux window)."""

    def __init__(self, uploader: ui.upload, native: bool, portal: bool):
        self.uploader = uploader
        self.native, self.portal = native, portal
        self.paths: list[Path] = []
        self.uploads: set[Path] = set()  # paths of uploaded files, deleted when unselected
        self.folder: Path | None = None  # the picked folder, while its files are selected
        self.ignored = 0  # files in the folder that aren't media files
        self.export = False  # also save a copy in <folder>/transcriptions
        self.uploading = False
        self.on_change: Callable[[], None] = lambda: None

    @property
    def names(self) -> list[str]:
        return [path.name for path in self.paths]

    @property
    def export_dir(self) -> Path | None:
        return self.folder / "transcriptions" if self.export and self.folder else None

    # --- changing the selection ---------------------------------------------------------

    def add_paths(self, paths: list[Path], folder: Path | None = None) -> None:
        """A folder replaces the selection; files are added to it."""
        if folder is not None:
            self.clear()
        self.paths += [path for path in paths if path not in self.paths]
        self.folder, self.export = folder, False
        self.on_change()

    def add_folder(self, folder: str | None) -> None:
        if folder:
            from aTrain_core.discovery import discover_media_files

            folder_path = Path(folder)
            files = discover_media_files(folder_path)
            self.ignored = ignored_files(folder_path, files)
            self.add_paths(files, folder_path)

    def remove(self, index: int) -> None:
        self._discard(self.paths.pop(index))
        if not self.paths:
            self.folder = None
        self.on_change()

    def clear(self) -> None:
        for path in self.paths:
            self._discard(path)
        self.paths, self.folder = [], None
        self.on_change()

    def _discard(self, path: Path) -> None:
        if path in self.uploads:
            self.uploads.discard(path)
            shutil.rmtree(path.parent, ignore_errors=True)

    # --- picking, uploading and dropping ------------------------------------------------

    async def browse_files(self) -> None:
        if not self.native:
            self.uploader.run_method("pickFiles")
            return
        self.add_paths([Path(p) for p in await self._pick(folder=False)])

    async def browse_folder(self) -> None:
        picked = await self._pick(folder=True)
        self.add_folder(picked[0] if picked else None)

    async def _pick(self, folder: bool) -> list[str]:
        if self.portal:  # the portal call blocks; in a thread so the UI stays connected
            return await run.io_bound(pick_native, folder)
        return await pick_in_window(folder)

    def upload_started(self) -> None:
        self.uploading = True
        self.on_change()

    async def uploaded(self, event: events.MultiUploadEventArguments) -> None:
        from aTrain.utils.transcription import stage_upload

        paths = []
        try:
            for file in event.files:
                paths.append(await stage_upload(file))
        except Exception as e:
            ui.notify(f"The upload failed: {e}", color="negative", multi_line=True)
        finally:
            self.uploads.update(paths)
            self.uploading = False
            self.add_paths(paths)

    def upload_failed(self) -> None:
        ui.notify("The upload failed. Please try again.", color="negative")
        self.uploading = False
        self.on_change()

    async def add_dropped(self, event: events.GenericEventArguments) -> None:
        """The paths of a drop in the Linux window (see aTrain.utils.linux_drop)."""
        files, unreadable, unsupported = check_dropped([Path(p) for p in event.args])
        if unsupported:
            ui.notify("Only audio and video files can be added")
        if files:
            self.add_paths(files)
        if not unreadable:
            return
        if not FLATPAK:
            names = ", ".join(path.name for path in unreadable)
            ui.notify(f"aTrain can't open {names}.", color="negative", multi_line=True)
            return
        picked, folder = await flatpak_portal.choose_dropped(unreadable[0])
        if folder:
            self.add_folder(picked[0] if picked else None)
        else:
            self.add_paths([Path(p) for p in picked])

    # --- adding the jobs ----------------------------------------------------------------

    async def submit(self) -> None:
        """Add one job per file. The selection stays if they can't be added."""
        from aTrain.utils.transcription import start_paths

        if await start_paths(self.paths, self.export_dir):
            # the uploaded files now belong to their jobs
            self.paths, self.uploads, self.folder = [], set(), None
            self.on_change()


def check_dropped(paths: list[Path]) -> tuple[list[Path], list[Path], list[str]]:
    """The media files among dropped paths (a folder adds its media files), the paths that
    can't be read (outside a Flatpak's sandbox) and the names of other files."""
    from aTrain_core.discovery import discover_media_files

    allowed = {extension.lower() for extension in load_formats()}
    files, unreadable, unsupported = [], [], []
    for path in paths:
        if path.suffix and path.suffix.lower() not in allowed and not path.is_dir():
            unsupported.append(path.name)
        elif not os.access(path, os.R_OK):
            unreadable.append(path)  # a media file, or (no extension) likely a folder
        elif path.is_dir():
            files += discover_media_files(path)
        else:
            files.append(path)
    return files, unreadable, unsupported


def ignored_files(folder: Path, files: list[Path]) -> int:
    """The visible files in the folder that aren't supported media files."""
    visible = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    return visible - len(files)


async def pick_in_window(folder: bool) -> list[str]:
    """The dialog of the desktop window (Windows, macOS), which returns paths."""
    import webview  # type: ignore

    if folder:
        result = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
    else:
        types = "Audio and video files (" + ";".join("*" + ext for ext in load_formats()) + ")"
        result = await app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=(types,)
        )
    return list(result or [])


def pick_native(directory: bool, folder: Path | None = None) -> list[str]:
    """The desktop portal's file chooser (Linux/Flatpak), which returns real paths.
    `folder`: where it opens (ignored by portals older than version 3)."""
    try:
        import gi  # type: ignore

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib  # type: ignore

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.FileChooser",
            None,
        )

        token = f"atrain{os.getpid()}"
        options = {
            "handle_token": GLib.Variant("s", token),
            "multiple": GLib.Variant("b", not directory),
            "directory": GLib.Variant("b", directory),
        }
        if folder is not None:  # a null-terminated byte string
            options["current_folder"] = GLib.Variant("ay", os.fsencode(folder) + b"\0")

        result = proxy.call_sync(
            "OpenFile",
            GLib.Variant(
                "(ssa{sv})", ("", "Select Folder" if directory else "Select Files", options)
            ),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        handle = result.unpack()[0]

        request = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            handle,
            "org.freedesktop.portal.Request",
            None,
        )

        filenames: list[str] = []
        loop = GLib.MainLoop()

        def on_response(_proxy, _sender, _signal, params):
            response, results = params.unpack()
            if response == 0:
                for uri in results.get("uris") or []:
                    filenames.append(Gio.File.new_for_uri(uri).get_path())
            loop.quit()

        request.connect("g-signal", on_response)
        loop.run()
        return filenames
    except Exception as exc:
        print(f"Flatpak portal file dialog failed: {exc}")
        return []

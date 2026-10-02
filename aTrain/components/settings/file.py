import os
from pathlib import Path

from aTrain_core.globals import FLATPAK, LINUX
from aTrain_core.settings import load_formats
from nicegui import app, run, ui

PREVIEW_FILES = 5


class CustomUpload(ui.upload):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on("added", self.set_added)
        self.set_select()

    def pick_files(self):
        self.reset()
        self.set_select()
        self.run_method("pickFiles")

    def upload(self):
        self.run_method("upload")

    def set_added(self, event=None):
        count = len(event.args) if event is not None and isinstance(event.args, list) else 1
        self.file_text = "1 File Added" if count == 1 else f"{count} Files Added"
        self.file_icon = "file_present"

    def set_select(self):
        self.file_text = "Select File"
        self.file_icon = "attach_file"


def folder_summary(folder: Path, files: list[Path]) -> str:
    """ "12 supported files found (3 other files ignored)", the first names and "and 7 more"."""
    others = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")) - len(
        files
    )
    text = f"{len(files)} supported files found" + (
        f" ({others} other files ignored)" if others else ""
    )
    names = [f.name for f in files[:PREVIEW_FILES]]
    if len(files) > PREVIEW_FILES:
        names.append(f"and {len(files) - PREVIEW_FILES} more")
    return "\n".join([text, *names])


def input_file() -> CustomUpload:
    """Pick one or several files, or (in a native window) a folder. The page reads
    `selected_paths` and `export_dir`; browser uploads go through the uploader."""
    allowed_files = "".join(x for x in str(load_formats()) if x not in "[]'")
    uploader = CustomUpload(multiple=True).classes("hidden")
    uploader.props(f"accept='{allowed_files}' batch")
    uploader.selected_paths = []
    uploader.export_dir = None
    native = app.native.main_window is not None
    portal = (FLATPAK or LINUX) and native

    with ui.column().classes("gap-2"):
        ui.label("Select File").classes("font-bold text-dark text-md")
        ui.separator()
        mode = ui.toggle(["Files", "Folder"], value="Files").props("no-caps unelevated")
        mode.set_visibility(native)
        with ui.button() as select_button:
            select_button.props("color=gray-100 text-color=dark align=left")
            select_button.props("unelevated no-caps :ripple=false")
            select_button.classes("w-full h-full")
        file_label = ui.label("").classes("text-sm text-gray-500 whitespace-pre-line")
        export = ui.checkbox("Also save a copy next to the source files").classes("text-sm")
        export.set_visibility(False)
    uploader.mode = mode

    def show(paths: list[Path], text: str, folder: Path | None = None):
        uploader.selected_paths = paths
        file_label.text = text
        export.set_visibility(folder is not None)
        export.value = False
        uploader.export_folder = folder
        if folder is not None and not os.access(folder, os.W_OK):
            file_label.text += (
                "\nThis folder is read-only: a copy next to the files is not possible."
            )
            export.disable()
        else:
            export.enable()

    def update_export(e):
        folder = getattr(uploader, "export_folder", None)
        uploader.export_dir = folder / "transcriptions" if e.value and folder else None

    export.on_value_change(update_export)

    def show_folder(folder: str | None):
        if not folder:
            return
        from aTrain_core.discovery import discover_media_files

        folder_path = Path(folder)
        files = discover_media_files(folder_path)
        show(files, folder_summary(folder_path, files), folder_path)

    def on_mode_change():
        uploader.reset()
        show([], "")
        folder_mode = mode.value == "Folder"
        uploader.file_text = "Select Folder" if folder_mode else "Select File"
        uploader.file_icon = "folder_open" if folder_mode else "attach_file"
        select_button.text = uploader.file_text  # the portal button isn't bound

    mode.on_value_change(on_mode_change)

    if not portal:
        select_button.bind_text(uploader, "file_text")
        select_button.bind_icon(uploader, "file_icon")

        async def on_select():
            if mode.value == "Files":
                show([], "")
                uploader.pick_files()
                return
            import webview  # type: ignore

            result = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
            show_folder(result[0] if result else None)
            uploader.file_text = "Folder selected" if uploader.selected_paths else "Select Folder"

        select_button.on_click(on_select)
        return uploader

    select_button.text = "Select Files"

    def pick_native(directory: bool) -> list[str]:
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

    async def on_pick():
        # The portal call blocks; run it in a thread so the UI stays connected.
        picked = await run.io_bound(pick_native, mode.value == "Folder")
        if not picked:
            return
        if mode.value == "Folder":
            show_folder(picked[0])
            return
        paths = [Path(p) for p in picked]
        show(paths, "\n".join(p.name for p in paths))

    select_button.on_click(on_pick)

    return uploader

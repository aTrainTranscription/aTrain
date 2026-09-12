import os

from aTrain_core.globals import FLATPAK, LINUX
from aTrain_core.settings import load_formats
from nicegui import ui


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

    def set_added(self):
        self.file_text = "1 File Added"
        self.file_icon = "file_present"
        self.selection_mode = "file"

    def set_select(self):
        self.file_text = "Select File"
        self.file_icon = "attach_file"


def pick_folder_native() -> str | None:
    """Open a local folder picker on the machine running the app."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        folder = filedialog.askdirectory(title="Select Folder")
        return folder or None
    finally:
        root.destroy()


def input_file() -> CustomUpload:
    allowed_files = "".join(x for x in str(load_formats()) if x not in "[]'")
    uploader = CustomUpload().classes("hidden")
    uploader.props(f"accept='{allowed_files}'")
    uploader.selected_folder_path = None
    uploader.selected_folder_name = None
    uploader.selection_mode = "file"

    with ui.column().classes("gap-2"):
        ui.label("Input").classes("font-bold text-dark text-md")
        ui.separator()
        with ui.row().classes("w-full gap-2"):
            file_mode_button = ui.button("File", icon="description")
            file_mode_button.props("unelevated no-caps")
            file_mode_button.classes("flex-1")
            folder_mode_button = ui.button("Folder", icon="folder")
            folder_mode_button.props("unelevated no-caps")
            folder_mode_button.classes("flex-1")
        mode_label = ui.label("File mode").classes("text-sm text-gray-500")
        with ui.column().classes("w-full gap-1") as file_panel:
            with ui.button() as select_button:
                select_button.props("color=gray-100 text-color=dark align=left")
                select_button.props("unelevated no-caps :ripple=false")
                select_button.classes("w-full h-full")
            file_label = ui.label("No file selected").classes("text-sm text-gray-500")
        with ui.column().classes("w-full gap-1") as folder_panel:
            with ui.button("Select Folder", icon="folder") as folder_button:
                folder_button.props("color=gray-100 text-color=dark align=left")
                folder_button.props("unelevated no-caps :ripple=false")
                folder_button.classes("w-full h-full")
            folder_label = ui.label("No folder selected").classes("text-sm text-gray-500")

    def set_selection_mode(mode: str):
        uploader.selection_mode = mode
        file_panel.visible = mode == "file"
        folder_panel.visible = mode == "folder"
        mode_label.text = "File mode" if mode == "file" else "Folder mode"
        style_mode_button(file_mode_button, mode == "file")
        style_mode_button(folder_mode_button, mode == "folder")

    def style_mode_button(button, selected: bool):
        button.props(remove="color=dark color=gray-100 text-color=white text-color=dark")
        if selected:
            button.props("color=dark text-color=white")
        else:
            button.props("color=gray-100 text-color=dark")

    file_mode_button.on_click(lambda: set_selection_mode("file"))
    folder_mode_button.on_click(lambda: set_selection_mode("folder"))
    set_selection_mode("file")

    if not (FLATPAK or LINUX):
        select_button.bind_text(uploader, "file_text")
        select_button.bind_icon(uploader, "file_icon")
        select_button.on_click(uploader.pick_files)

        def on_pick_folder():
            path = pick_folder_native()
            if not path:
                return
            uploader.selection_mode = "folder"
            uploader.selected_folder_path = path
            uploader.selected_folder_name = os.path.basename(path)
            folder_label.text = uploader.selected_folder_name
            uploader.file_text = "Select File"
            uploader.file_icon = "attach_file"
            set_selection_mode("folder")

        folder_button.on_click(on_pick_folder)
        return uploader

    uploader.selected_content = None
    uploader.selected_name = None
    uploader.selected_path = None
    select_button.text = "Select File"

    def pick_file_native(directory: bool = False) -> str | None:
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
                "multiple": GLib.Variant("b", False),
                "directory": GLib.Variant("b", directory),
            }

            result = proxy.call_sync(
                "OpenFile",
                GLib.Variant("(ssa{sv})", ("", "Select File", options)),
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

            filename: str | None = None
            loop = GLib.MainLoop()

            def on_response(_proxy, _sender, _signal, params):
                nonlocal filename
                response, results = params.unpack()
                if response == 0:
                    uris = results.get("uris")
                    if uris:
                        uri = uris[0]
                        filename = Gio.File.new_for_uri(uri).get_path()
                loop.quit()

            request.connect("g-signal", on_response)
            loop.run()
            return filename
        except Exception as exc:
            print(f"Flatpak portal file dialog failed: {exc}")
            return None

    def on_pick():
        path = pick_file_native()
        if not path:
            return
        uploader.selection_mode = "file"
        uploader.selected_path = path
        uploader.selected_name = os.path.basename(path)
        file_label.text = uploader.selected_name
        set_selection_mode("file")

    select_button.on_click(on_pick)

    def on_pick_folder_flatpak():
        path = pick_file_native(directory=True)
        if not path:
            return
        uploader.selection_mode = "folder"
        uploader.selected_folder_path = path
        uploader.selected_folder_name = os.path.basename(path)
        folder_label.text = uploader.selected_folder_name
        set_selection_mode("folder")

    folder_button.on_click(on_pick_folder_flatpak)

    return uploader

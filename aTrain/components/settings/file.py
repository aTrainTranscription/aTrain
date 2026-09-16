import os

from aTrain_core.globals import FLATPAK, LINUX
from aTrain_core.settings import load_formats
from nicegui import app, ui


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

    def set_select(self):
        self.file_text = "Select File"
        self.file_icon = "attach_file"


def input_file() -> CustomUpload:
    allowed_files = "".join(x for x in str(load_formats()) if x not in "[]'")
    uploader = CustomUpload().classes("hidden")
    uploader.props(f"accept='{allowed_files}'")

    with ui.column().classes("gap-2") as file_column:
        ui.label("Select File").classes("font-bold text-dark text-md")
        ui.separator()
        with ui.button() as select_button:
            select_button.props("color=gray-100 text-color=dark align=left")
            select_button.props("unelevated no-caps :ripple=false")
            select_button.classes("w-full h-full")

    if not (FLATPAK or LINUX) or app.native.main_window is None:
        select_button.bind_text(uploader, "file_text")
        select_button.bind_icon(uploader, "file_icon")
        select_button.on_click(uploader.pick_files)
        return uploader

    with file_column:
        file_label = ui.label("No file selected").classes("text-sm text-gray-500")

    uploader.selected_content = None
    uploader.selected_name = None
    uploader.selected_path = None
    select_button.text = "Select File"

    def pick_file_native() -> str | None:
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
                "directory": GLib.Variant("b", False),
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
        uploader.selected_path = path
        uploader.selected_name = os.path.basename(path)
        file_label.text = uploader.selected_name

    select_button.on_click(on_pick)

    return uploader

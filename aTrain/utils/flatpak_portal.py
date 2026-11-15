"""The file chooser of the desktop portals (Linux, Flatpak), which returns real paths."""

import os


def pick_native(directory: bool) -> list[str]:
    """The desktop portal's file chooser (Linux/Flatpak), which returns real paths."""
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

"""Files through the desktop portals: the file chooser (Linux), and in a Flatpak the files
outside the sandbox.

A Flatpak can read only the files the user gives it through a portal: dropped files through
the file transfer portal, other files through the file chooser. Light to import, since the
window process (aTrain.utils.linux_drop) uses it too.
"""

import os
from pathlib import Path

# A drag offers its files to sandboxed apps under one of these types, GTK 4 apps (e.g. GNOME
# Files) under the first, older GTK under the second. The data is a key for RetrieveFiles.
TRANSFER_TARGETS = ("application/vnd.portal.filetransfer", "application/vnd.portal.files")


def transfer_target(offered: list[str]) -> str | None:
    """The file transfer type a drag offers, if any."""
    return next((target for target in TRANSFER_TARGETS if target in offered), None)


def transfer_key(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip("\0 \r\n")


def retrieve_files(key: str) -> list[str]:
    """The files of a file transfer, as paths in the document portal that the sandbox can
    read."""
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = bus.call_sync(
        "org.freedesktop.portal.Documents",
        "/org/freedesktop/portal/documents",
        "org.freedesktop.portal.FileTransfer",
        "RetrieveFiles",
        GLib.Variant("(sa{sv})", (key, {})),
        GLib.VariantType("(as)"),
        Gio.DBusCallFlags.NONE,
        10_000,
        None,
    )
    return list(result.unpack()[0])


async def choose_dropped(dropped: Path) -> tuple[list[str], bool]:
    """A dropped path the sandbox can't read (dragged from an app that doesn't offer the file
    transfer portal): the portal's file chooser opens where it is, for one more click.
    Returns the picked paths and whether a folder was asked for (no extension)."""
    from nicegui import run, ui

    folder = not dropped.suffix
    kind = "the folder " if folder else ""
    ui.notify(f"Select {kind}{dropped.name} to give aTrain access to it.", multi_line=True)
    return await run.io_bound(pick_native, folder, dropped.parent), folder


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

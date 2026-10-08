"""File drops in the Linux window. Runs in pywebview's window process, not in the server.

WebKitGTK hands a page none of the files dropped from a file manager, only the first one's
URI, and it never asks for the file transfer portal, so in a Flatpak not even that file can
be read. GTK itself gets all of them. This asks the drag for the portal's key (in a Flatpak,
see aTrain.utils.flatpak_portal) or the URI list (outside), and sends the page the paths as
the event "atrain_drop".
"""

import json
import threading
from urllib.parse import unquote, urlparse

from aTrain.utils import flatpak_portal
from aTrain_core.globals import FLATPAK

EVENT = "atrain_drop"
URI_LIST = "text/uri-list"


def start() -> None:
    """`webview.start(func=start)`: runs in its own thread once the GUI has started."""
    import webview
    from gi.repository import GLib

    window = webview.windows[0]
    window.events.shown.wait()
    GLib.idle_add(_connect, window.native)


def _connect(gtk_window) -> bool:
    view = _find_webview(gtk_window)
    if view is not None:
        Drops().connect(view)
    return False  # run once


def _find_webview(widget):
    if type(widget).__gtype__.name == "WebKitWebView":
        return widget
    children = widget.get_children() if hasattr(widget, "get_children") else []
    for child in children:
        found = _find_webview(child)
        if found is not None:
            return found
    return None


def _atom(name: str):
    from gi.repository import Gdk

    return Gdk.Atom.intern(name, False)


def paths_from_uris(uris: list[str]) -> list[str]:
    return [unquote(urlparse(uri).path) for uri in uris if uri.startswith("file://")]


class Drops:
    """The data of the current drag, asked for while it hovers (the offer is alive then) and
    sent to the page once it is dropped and the data is in, in whichever order."""

    def __init__(self):
        self.context = None  # the drag the data below belongs to
        self.paths: list[str] = []
        self.key: str | None = None
        self.asked: str | None = None  # the portal target asked for
        self.dropped = False
        self.sent = False

    def connect(self, view) -> None:
        view.connect("drag-motion", self.on_motion)
        view.connect("drag-data-received", self.on_data)
        view.connect("drag-drop", self.on_drop)

    def reset(self, context) -> None:
        self.context, self.paths, self.key, self.asked = context, [], None, None
        self.dropped = self.sent = False

    def on_motion(self, view, context, x, y, time) -> bool:
        # GTK may reuse the context object: a motion after a drop is a new drag
        if context is not self.context or self.dropped:
            self.reset(context)
            offered = [target.name() for target in context.list_targets()]
            target = flatpak_portal.transfer_target(offered)
            if FLATPAK and target is not None:
                self.asked = target
                view.drag_get_data(context, _atom(target), time)
        return False  # WebKit handles the motion

    def on_data(self, view, context, x, y, data, info, time) -> None:
        if context is not self.context:
            return
        target = data.get_target().name()
        if target == self.asked:
            view.stop_emission_by_name("drag-data-received")  # ours, not WebKit's
            self.key = flatpak_portal.transfer_key(data.get_data() or b"")
        elif target == URI_LIST:  # asked for by WebKit; it gets it too
            self.paths = paths_from_uris(data.get_uris() or [])
        self.send_when_ready(view)

    def on_drop(self, view, context, x, y, time) -> bool:
        if context is self.context:
            self.dropped = True
            self.send_when_ready(view)
        return False  # WebKit finishes the drop

    def send_when_ready(self, view) -> None:
        ready = self.key if self.asked else self.paths
        if self.dropped and ready and not self.sent:
            self.sent = True
            # the portal call blocks: not on GTK's thread
            threading.Thread(
                target=self.send, args=(view, self.key, self.paths), daemon=True
            ).start()

    def send(self, view, key: str | None, paths: list[str]) -> None:
        if key:
            try:
                paths = flatpak_portal.retrieve_files(key)
            except Exception as error:  # keep the plain paths; the page reports them
                print(f"File transfer portal failed: {error}")
        if paths:
            from gi.repository import GLib

            script = f"emitEvent({json.dumps(EVENT)}, {json.dumps(paths)})"
            GLib.idle_add(view.evaluate_javascript, script, -1, None, None, None, None, None)

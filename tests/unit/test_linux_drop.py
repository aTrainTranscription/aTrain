"""The window-process side of file drops in the Linux window, with stand-ins for GTK."""

from types import SimpleNamespace

import pytest
from aTrain.utils import linux_drop
from aTrain.utils.flatpak_portal import transfer_key, transfer_target
from aTrain.utils.linux_drop import Drops, paths_from_uris


def atom(name):
    return SimpleNamespace(name=lambda: name)


class View:
    def __init__(self):
        self.asked, self.stopped = [], []

    def drag_get_data(self, context, target, time):
        self.asked.append(target)

    def stop_emission_by_name(self, signal):
        self.stopped.append(signal)


class Data:
    def __init__(self, target, data=b"", uris=()):
        self.target, self.data, self.uris = target, data, list(uris)

    def get_target(self):
        return atom(self.target)

    def get_data(self):
        return self.data

    def get_uris(self):
        return self.uris


def context(*targets):
    return SimpleNamespace(list_targets=lambda: [atom(t) for t in targets])


@pytest.fixture
def sent(monkeypatch):
    """The (key, paths) a drop sends, instead of a thread that calls the portal."""
    calls = []
    monkeypatch.setattr(Drops, "send", lambda self, view, key, paths: calls.append((key, paths)))
    monkeypatch.setattr(
        linux_drop.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )
    return calls


def test_paths_from_uris():
    uris = ["file:///home/me/My%20Music/a.mp3", "https://example.com/x.mp3", "file:///b.wav"]
    assert paths_from_uris(uris) == ["/home/me/My Music/a.mp3", "/b.wav"]


def test_transfer_key_and_target():
    assert transfer_key(b"1234-abcd\0") == "1234-abcd"
    offered = ["text/uri-list", "application/vnd.portal.files"]
    assert transfer_target(offered) == "application/vnd.portal.files"
    assert transfer_target(["text/uri-list"]) is None


@pytest.mark.parametrize("data_first", [True, False])
def test_uri_list_outside_a_flatpak(sent, monkeypatch, data_first):
    monkeypatch.setattr(linux_drop, "FLATPAK", False)
    drops, view = Drops(), View()
    drag = context("text/uri-list", "application/vnd.portal.filetransfer")
    drops.on_motion(view, drag, 0, 0, 1)
    assert view.asked == []  # no portal needed, WebKit asks for the URI list itself
    uris = Data("text/uri-list", uris=["file:///a.mp3", "file:///b.mp3"])

    steps = [
        lambda: drops.on_data(view, drag, 0, 0, uris, 0, 1),
        lambda: drops.on_drop(view, drag, 0, 0, 1),
    ]
    for step in steps if data_first else reversed(steps):
        step()

    assert sent == [(None, ["/a.mp3", "/b.mp3"])]  # all files, not only the first
    assert view.stopped == []  # WebKit gets its data too


def test_portal_key_in_a_flatpak(sent, monkeypatch):
    monkeypatch.setattr(linux_drop, "FLATPAK", True)
    monkeypatch.setattr(linux_drop, "_atom", lambda name: name)
    drops, view = Drops(), View()
    drag = context("text/uri-list", "application/vnd.portal.filetransfer")

    drops.on_motion(view, drag, 0, 0, 1)
    drops.on_motion(view, drag, 5, 5, 2)  # asked once per drag
    assert view.asked == ["application/vnd.portal.filetransfer"]
    drops.on_data(view, drag, 0, 0, Data("text/uri-list", uris=["file:///home/a.mp3"]), 0, 1)
    drops.on_drop(view, drag, 0, 0, 1)
    assert sent == []  # waits for the key
    key = Data("application/vnd.portal.filetransfer", data=b"key-1\0")
    drops.on_data(view, drag, 0, 0, key, 0, 1)

    assert sent == [("key-1", ["/home/a.mp3"])]
    assert view.stopped == ["drag-data-received"]  # the key isn't for WebKit


def test_a_new_drag_starts_over(sent, monkeypatch):
    monkeypatch.setattr(linux_drop, "FLATPAK", False)
    drops, view = Drops(), View()
    first, second = context("text/uri-list"), context("text/uri-list")
    drops.on_motion(view, first, 0, 0, 1)
    drops.on_data(view, first, 0, 0, Data("text/uri-list", uris=["file:///a.mp3"]), 0, 1)
    drops.on_motion(view, second, 0, 0, 2)  # the first drag left without a drop

    drops.on_drop(view, second, 0, 0, 2)
    drops.on_data(view, second, 0, 0, Data("text/uri-list", uris=["file:///b.mp3"]), 0, 2)

    assert sent == [(None, ["/b.mp3"])]


def test_the_next_drag_works_with_a_reused_context(sent, monkeypatch):
    monkeypatch.setattr(linux_drop, "FLATPAK", False)
    drops, view = Drops(), View()
    drag = context("text/uri-list")
    for name in ("a.mp3", "b.mp3"):  # two drags; GTK hands over the same context object
        drops.on_motion(view, drag, 0, 0, 1)
        drops.on_data(view, drag, 0, 0, Data("text/uri-list", uris=[f"file:///{name}"]), 0, 1)
        drops.on_drop(view, drag, 0, 0, 1)

    assert sent == [(None, ["/a.mp3"]), (None, ["/b.mp3"])]

import socket

from aTrain.utils import ports


def test_find_available_port_skips_busy_ports(monkeypatch):
    bound_addresses = []

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            self.address = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def bind(self, address):
            bound_addresses.append(address)
            if address == ("127.0.0.1", 8080):
                raise OSError("busy")
            self.address = address

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: FakeSocket())

    assert ports.find_available_port(8080) == 8081
    assert bound_addresses == [
        ("127.0.0.1", 8080),
        ("127.0.0.1", 8081),
        ("", 8081),
    ]

"""The host check of a server bound to loopback (#300), against the running app.

A request under a foreign host name, as a page would send it after DNS
rebinding, and a socket.io handshake from a foreign origin are rejected. The
other tests in this directory run a real browser through the same check.
"""

import http.client
from urllib.parse import urlsplit

import pytest

SOCKET_IO_HANDSHAKE = "/_nicegui_ws/socket.io/?EIO=4&transport=polling"


def _status(server: str, path: str, headers: dict[str, str]) -> int:
    url = urlsplit(server)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    try:
        connection.request("GET", path, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


@pytest.mark.parametrize("path", ["/archive", SOCKET_IO_HANDSHAKE])
def test_foreign_host_name_is_rejected(atrain_server: str, path: str) -> None:
    status = _status(atrain_server, path, {"Host": "rebound.example:8080"})
    assert status == 400, f"{path} under a foreign host name answered {status}"


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (None, 200),  # same origin as the server
        ("http://localhost:9000", 400),  # another local web server
        ("https://example.com", 400),
    ],
)
def test_socket_io_accepts_only_the_same_origin(
    atrain_server: str, origin: str | None, expected: int
) -> None:
    origin = origin or atrain_server
    status = _status(atrain_server, SOCKET_IO_HANDSHAKE, {"Origin": origin})
    assert status == expected, f"socket.io handshake from {origin} answered {status}"

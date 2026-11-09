"""Bind address and the host and origin check of the local server (#300).

Once a website's domain resolves to 127.0.0.1 (DNS rebinding), a page from
that site reaches aTrain's local server under its own domain. A server bound
to 127.0.0.1 or localhost therefore answers only to those two host names.
NiceGUI accepts socket.io connections from every origin. Here only pages from
the server's own origin may connect.
"""

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def bind_host(host: str | None) -> str:
    """Return the address `aTrain start` binds to. Without `--host` it is 127.0.0.1,
    in the native window and with `--no-native`."""
    return host or LOOPBACK_HOSTS[0]


def host_check_applies(host: str, allow_any_host: bool) -> bool:
    """True when `aTrain start` turns on the host and origin check. That happens when
    the server binds to 127.0.0.1 or localhost and `--allow-any-host` is not set."""
    return not allow_any_host and host in LOOPBACK_HOSTS


def restrict_to_loopback_hosts() -> None:
    """Reject requests to other host names and socket.io connections from other origins."""
    # These imports stay inside the function. `aTrain init` (through aTrain/app.py)
    # and the unit tests load this module without the GUI extras, so nicegui can be
    # missing.
    from nicegui import app, core
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
    # NiceGUI allows every origin on socket.io. None restores engineio's default:
    # only pages from the same origin as the request may connect.
    core.sio.eio.cors_allowed_origins = None

"""Host and origin check for the local server (#300).

Once a website's domain resolves to 127.0.0.1 (DNS rebinding), a page from
that site reaches aTrain's local server under its own domain. A server bound
to 127.0.0.1 or localhost therefore answers only to those two host names.
Pages from any other origin may not open socket.io either, which NiceGUI
otherwise allows.
"""

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def host_check_applies(host: str | None, native: bool, allow_any_host: bool) -> bool:
    """Whether `aTrain start` turns the check on.

    Without `--allow-any-host`, it applies when the server binds to 127.0.0.1
    or localhost. Without `--host`, the native window binds to 127.0.0.1 and
    `--no-native` to all interfaces.
    """
    if allow_any_host:
        return False
    return host in LOOPBACK_HOSTS or (not host and native)


def restrict_to_loopback_hosts() -> None:
    """Reject requests to other host names and socket.io connections from other origins."""
    # Imported here: `aTrain init` (through aTrain/app.py) and the unit tests load
    # this module without the GUI extras installed.
    from nicegui import app, core
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
    # NiceGUI allows every origin on socket.io. None restores engineio's default:
    # only pages from the same origin as the request may connect.
    core.sio.eio.cors_allowed_origins = None

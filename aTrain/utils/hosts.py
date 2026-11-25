"""Bind address and the host and origin check of the local server (#300).

Once a website's domain resolves to 127.0.0.1 (DNS rebinding), a page from
that site reaches aTrain's local server under its own domain. A server bound
to 127.0.0.1 or localhost therefore answers only to those two host names.
NiceGUI accepts socket.io connections from every origin. Here only pages from
the server's own origin may connect. A reverse proxy on the same machine adds
its public host names with `--allowed-host`.
"""

from collections.abc import Iterable

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def bind_host(host: str | None) -> str:
    """Return the address `aTrain start` binds to. Without `--host` it is 127.0.0.1,
    in the native window and with `--no-native`."""
    return host or LOOPBACK_HOSTS[0]


def host_check_applies(host: str, allow_any_host: bool) -> bool:
    """True when `aTrain start` turns on the host and origin check. That happens when
    the server binds to 127.0.0.1 or localhost and `--allow-any-host` is not set."""
    return not allow_any_host and host in LOOPBACK_HOSTS


def allowed_hosts(extra_hosts: Iterable[str]) -> tuple[str, ...]:
    """Return the loopback names plus the `--allowed-host` names, lowercased and
    without duplicates. Raise ValueError for a name that can never match a Host
    header, such as one with a scheme, port or path."""
    hosts = list(LOOPBACK_HOSTS)
    for name in extra_hosts:
        host = name.strip().lower()
        if not host or ":" in host or "/" in host:
            raise ValueError(
                f"Invalid --allowed-host {name!r}: give a host name only, "
                "for example 'my.domain.com' or '*.domain.com'."
            )
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def restrict_hosts(hosts: Iterable[str]) -> None:
    """Reject requests to host names not in `hosts` and socket.io connections from
    other origins."""
    # These imports stay inside the function. `aTrain init` (through aTrain/app.py)
    # and the unit tests load this module without the GUI extras, so nicegui can be
    # missing.
    from nicegui import app, core
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    # NiceGUI allows every origin on socket.io. None restores engineio's default:
    # only pages from the same origin as the request may connect. Behind a proxy
    # that origin comes from the Host and X-Forwarded-Proto headers it passes on.
    core.sio.eio.cors_allowed_origins = None

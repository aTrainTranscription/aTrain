"""Unit tests for aTrain/utils/hosts.py - bind address and host check (#300).

NiceGUI-free, so they run in the lightweight `unit` CI job.
"""

import pytest
from aTrain.utils.hosts import allowed_hosts, bind_host, host_check_applies


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (None, "127.0.0.1"),  # native window and --no-native without --host
        ("", "127.0.0.1"),
        ("localhost", "localhost"),
        ("192.168.1.20", "192.168.1.20"),  # network mode needs an explicit --host
    ],
)
def test_binds_to_loopback_unless_host_is_given(host, expected):
    assert bind_host(host) == expected


@pytest.mark.parametrize(
    ("host", "allow_any_host", "expected"),
    [
        ("127.0.0.1", False, True),
        ("localhost", False, True),
        ("192.168.1.20", False, False),
        ("127.0.0.1", True, False),  # reverse proxy on the same machine
    ],
)
def test_host_check_only_when_bound_to_loopback(host, allow_any_host, expected):
    assert host_check_applies(host, allow_any_host) is expected, (
        f"host={host!r} allow_any_host={allow_any_host}"
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ([], ("127.0.0.1", "localhost")),
        (["my.domain.com"], ("127.0.0.1", "localhost", "my.domain.com")),
        ([" My.Domain.COM "], ("127.0.0.1", "localhost", "my.domain.com")),
        (["*.domain.com"], ("127.0.0.1", "localhost", "*.domain.com")),
        (["localhost", "a.org", "a.org"], ("127.0.0.1", "localhost", "a.org")),
    ],
)
def test_allowed_hosts_adds_proxy_host_names(extra, expected):
    assert allowed_hosts(extra) == expected


@pytest.mark.parametrize(
    "bad", ["", "  ", "https://my.domain.com", "my.domain.com:443", "my.domain.com/atrain"]
)
def test_allowed_hosts_rejects_what_never_matches_a_host_header(bad):
    with pytest.raises(ValueError):
        allowed_hosts([bad])

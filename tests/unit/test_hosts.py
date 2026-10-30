"""Unit tests for aTrain/utils/hosts.py - when `aTrain start` turns on the host check (#300).

NiceGUI-free, so they run in the lightweight `unit` CI job.
"""

import pytest
from aTrain.utils.hosts import host_check_applies


@pytest.mark.parametrize(
    ("host", "native", "allow_any_host", "expected"),
    [
        (None, True, False, True),  # native window, how the installed apps run
        ("", True, False, True),  # NiceGUI binds an empty host to 127.0.0.1 too
        (None, False, False, False),  # --no-native without --host binds to all interfaces
        ("127.0.0.1", False, False, True),
        ("localhost", False, False, True),
        ("192.168.1.20", False, False, False),
        ("192.168.1.20", True, False, False),
        ("127.0.0.1", False, True, False),  # reverse proxy on the same machine
        (None, True, True, False),
    ],
)
def test_host_check_only_when_bound_to_loopback(host, native, allow_any_host, expected):
    assert host_check_applies(host, native, allow_any_host) is expected, (
        f"host={host!r} native={native} allow_any_host={allow_any_host}"
    )

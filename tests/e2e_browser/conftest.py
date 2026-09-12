"""Fixtures for real-browser e2e tests driven by Playwright.

`atrain_server` starts `aTrain start --no-native` as a subprocess for the whole
test session, polls until it serves HTTP 200 on http://127.0.0.1:8080, and
yields that URL. Terminated on teardown.

Individual tests receive Playwright's own `page` / `browser` fixtures from
pytest-playwright and drive real Chromium against the running server.

Kept in its own directory so `tests/ui/conftest.py`'s
`pytest_plugins = ["nicegui.testing.user_plugin"]` does not apply here - the
in-process NiceGUI User fixture and a real browser can't share the same
event loop.
"""

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Generator

import pytest

BASE_URL = "http://127.0.0.1:8080"
BOOT_TIMEOUT_S = 90


@pytest.fixture(scope="session")
def atrain_server() -> Generator[str, None, None]:
    # WAKEPY_FAKE_SUCCESS mirrors tests/ui/test_boot_serve.py - wakepy has no
    # backend on headless CI and raises without it.
    env = {**os.environ, "WAKEPY_FAKE_SUCCESS": "1"}
    # The subprocess must not look like it runs inside pytest: nicegui>=3's
    # ui.run sees PYTEST_CURRENT_TEST and then requires the screen-test port.
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.Popen(
        ["aTrain", "start", "--no-native"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(f"aTrain exited early (code {proc.returncode}):\n{output}")
            try:
                with urllib.request.urlopen(BASE_URL, timeout=2) as response:  # noqa: S310
                    if response.status == 200:
                        yield BASE_URL
                        return
            except (urllib.error.URLError, ConnectionError) as error:
                last_error = error
                time.sleep(1)
        raise RuntimeError(f"aTrain never served {BASE_URL} within {BOOT_TIMEOUT_S}s: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

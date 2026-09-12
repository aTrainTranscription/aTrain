"""UI boot smoke test: the app starts headless and serves the main page.

Runs `aTrain start --no-native` (NiceGUI as a plain web server, no pywebview
window) and polls until the page responds with HTTP 200. Because it boots the
full app, it also validates that the shipped dependency stack imports and the
server comes up.

A full click-through UI E2E (NiceGUI `Screen` fixture / Playwright) is a
follow-up: the in-process `User` fixture can't drive this page, which gates
its rendering on `client.connected()` plus a splash-screen background import.
"""

import os
import subprocess
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080"
BOOT_TIMEOUT_S = 90  # generous; the server comes up in ~5-7 s locally


def test_app_boots_and_serves():
    # `aTrain start` wraps the server in wakepy's `keep.running()`, which raises
    # on headless CI with no wakelock backend. WAKEPY_FAKE_SUCCESS is wakepy's
    # documented escape hatch for exactly this (CI / no D-Bus).
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
        last_error = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise AssertionError(f"aTrain exited early (code {proc.returncode}):\n{output}")
            try:
                with urllib.request.urlopen(URL, timeout=2) as response:  # noqa: S310
                    assert response.status == 200
                    body = response.read().decode("utf-8", "replace").lower()
                    assert "atrain" in body or "nicegui" in body
                    return
            except (urllib.error.URLError, ConnectionError) as error:
                last_error = error
                time.sleep(1)
        raise AssertionError(f"server never served {URL} within {BOOT_TIMEOUT_S}s: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

"""Tests for aTrain/utils/models.py::check_internet.

The check used urllib, whose TLS setup finds no CA certificates in the frozen
macOS app, while the download itself goes through huggingface_hub's session
(requests + certifi) and works. Every macOS download then failed with "not
connected to the internet" (#54, #107). The check must use the download's
session and report the real reason. Lives in tests/ui because the module
imports nicegui.
"""

import pytest
import requests
from aTrain.utils import models


class FakeSession:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def head(self, url, **kwargs):
        self.calls.append(url)
        if self.error:
            raise self.error


def test_uses_the_huggingface_hub_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(models, "get_session", lambda: session)

    models.check_internet()

    assert session.calls == ["https://huggingface.co"]


def test_error_message_carries_the_reason(monkeypatch):
    session = FakeSession(requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED"))
    monkeypatch.setattr(models, "get_session", lambda: session)

    with pytest.raises(ConnectionError, match="CERTIFICATE_VERIFY_FAILED"):
        models.check_internet()

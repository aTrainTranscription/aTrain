"""Tests for aTrain/utils/models.py::check_internet.

The check used urllib, whose TLS setup finds no CA certificates in the frozen
macOS app, while the download itself goes through huggingface_hub's session
(requests + certifi) and works. Every macOS download then failed with "not
connected to the internet" (#54, #107). Lives in tests/ui because the module
imports nicegui.
"""

import pytest
import requests
from aTrain.utils import models


def test_reports_the_tls_error_of_the_download_session(monkeypatch):
    """The check goes through the download's session and names the cause."""

    class FailingSession:
        def head(self, url, **kwargs):
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(models, "get_session", FailingSession)

    with pytest.raises(ConnectionError, match="CERTIFICATE_VERIFY_FAILED"):
        models.check_internet()

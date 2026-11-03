"""Readiness is emitted only after deferred imports and page construction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import aTrain_core.transcribe  # noqa: F401  keep page fixture imports synchronous
import pytest
from nicegui.testing import User


async def test_ready_page_can_open_advanced_settings(user: User, capsys):
    await user.open("/")
    await user.should_see("Start", retries=300)
    user.find(marker="open_advanced_settings").click()
    await user.should_see("Advanced Settings")
    output = capsys.readouterr().out
    assert "aTrain startup ready" in output
    assert "aTrain startup failed" not in output


@pytest.mark.parametrize("stage", ["splash_screen", "input_model", "advanced_settings"])
async def test_initialization_failure_never_reports_ready(user: User, monkeypatch, capsys, stage):
    from aTrain.pages import transcribe

    await user.open("/about")

    def fail(*args, **kwargs):
        raise ImportError("broken runtime dependency")

    monkeypatch.setattr(
        transcribe, stage, AsyncMock(side_effect=fail) if stage == "splash_screen" else fail
    )
    with user, pytest.raises(ImportError, match="broken runtime dependency"):
        await transcribe.page(SimpleNamespace(connected=AsyncMock()))
    output = capsys.readouterr().out
    assert "aTrain startup failed" in output
    assert "aTrain startup ready" not in output


async def test_partial_import_is_retried_on_reload(user: User, monkeypatch):
    from aTrain.components import splash_screen

    await user.open("/about")
    # torch succeeded on a prior visit, but transcribe failed to load.
    monkeypatch.setattr(splash_screen, "sys", SimpleNamespace(modules={"torch": object()}))

    async def import_module(function, *, name):
        if name == "aTrain_core.transcribe":
            raise ImportError("broken runtime dependency")

    importer = AsyncMock(side_effect=import_module)
    monkeypatch.setattr(splash_screen.run, "io_bound", importer)
    with user, pytest.raises(ImportError, match="broken runtime dependency"):
        await splash_screen.splash_screen()
    assert any(call.kwargs["name"] == "aTrain_core.transcribe" for call in importer.call_args_list)

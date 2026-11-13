"""The start page must stop quietly when its client is gone before it is built."""

import pytest
from aTrain.pages import transcribe


class DeletedClient:
    is_deleted = True

    async def connected(self):
        return None


class ClientDeletedDuringSplash:
    is_deleted = False

    async def connected(self):
        return None


async def test_page_returns_without_building_for_a_deleted_client(monkeypatch, transcribe):
    async def fail_splash():
        pytest.fail("splash_screen must not run for a deleted client")

    def fail_layout():
        pytest.fail("base_layout must not run for a deleted client")

    monkeypatch.setattr(transcribe, "splash_screen", fail_splash)
    monkeypatch.setattr(transcribe, "base_layout", fail_layout)

    await transcribe.page(DeletedClient())


async def test_page_returns_without_building_when_client_is_deleted_during_splash(monkeypatch, transcribe):
    client = ClientDeletedDuringSplash()

    async def splash_then_delete():
        client.is_deleted = True

    def fail_layout():
        pytest.fail("base_layout must not run for a deleted client")

    monkeypatch.setattr(transcribe, "splash_screen", splash_then_delete)
    monkeypatch.setattr(transcribe, "base_layout", fail_layout)

    await transcribe.page(client)

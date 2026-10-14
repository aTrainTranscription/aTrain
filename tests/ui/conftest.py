import pytest

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def temporary_queue(tmp_path, monkeypatch):
    """The pages start the app's queue service; keep its queue out of the user's aTrain folder."""
    from aTrain.utils import queue_ui
    from aTrain_core.jobs import JobStore

    monkeypatch.setattr(queue_ui, "QUEUE_ROOT", tmp_path / "queue")
    monkeypatch.setattr(
        queue_ui, "JobStore", lambda root: JobStore(root, tmp_path / "transcriptions")
    )
    monkeypatch.setattr(queue_ui, "_service", None)

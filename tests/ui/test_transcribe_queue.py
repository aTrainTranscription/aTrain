"""The transcribe page with its queue panel, with a real but paused QueueService on a
temporary store (it never starts a child)."""

import asyncio
from types import SimpleNamespace

import aTrain_core.globals
import aTrain_core.transcribe
import pytest
from aTrain.components.settings import file as file_component
from aTrain.utils import queue_ui
from aTrain_core.jobs import JobStatus, JobStore, QueueLockedError
from aTrain_core.queue_service import QueueService
from aTrain_core.settings import ComputeType, Device
from nicegui import ElementFilter, app, ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction
from tests.unit.test_jobs import make_spec

CHEAP_SETTINGS = {
    "model": "tiny",
    "language": "auto-detect",
    "speaker_detection": False,
    "speaker_count": 0,
    "GPU": False,
    "compute_type": "int8",
    "temperature_override": None,
    "initial_prompt": None,
    "cpu_threads": 0,
}


def no_child(arg):
    raise AssertionError("the UI tests never start a phase child")


@pytest.fixture
async def service(tmp_path, monkeypatch):
    service = QueueService(
        JobStore(tmp_path / "queue", tmp_path / "transcriptions"),
        launch_phase1=no_child,
        launch_phase2=no_child,
    )
    service.pause()
    await service.start()

    async def get_service():
        return service

    monkeypatch.setattr(queue_ui, "get_queue_service", get_service)
    yield service
    await service.stop()


def add(service, tmp_path, job_id, *statuses, **overrides):
    source = tmp_path / f"{job_id}.mp3"
    source.write_bytes(b"audio")
    values = {"device": Device.CPU, "compute_type": ComputeType.INT8, "speaker_detection": False}
    values.update(overrides)
    service.enqueue(
        [
            make_spec(
                id=job_id, source=source, display_name=f"{job_id}.mp3", export_dir=None, **values
            )
        ]
    )
    for status in statuses:
        service.store.update(job_id, status=status)


async def until(condition):
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


async def open_page(user: User):
    await user.open("/")
    await user.should_see(marker="add_to_queue", retries=200)


def one(user: User, marker: str):
    return next(iter(user.find(marker=marker).elements))


def row_button(user: User, job_id: str, icon: str) -> UserInteraction:
    """The icon button in the job's row of the queue list."""
    with user.client:
        buttons = set(ElementFilter(kind=ui.button, content=icon).within(marker=f"job_{job_id}"))
    return UserInteraction(user, buttons, None)


def ids(service):
    return [spec.id for spec, _ in service.jobs()]


S = JobStatus


# --- the page without jobs ------------------------------------------------------------


async def test_locked_queue_disables_add_to_queue(monkeypatch, user: User):
    async def locked():
        raise QueueLockedError("held")

    monkeypatch.setattr(queue_ui, "get_queue_service", locked)
    await user.open("/")
    await user.should_see(queue_ui.LOCKED_TEXT, retries=200)
    assert not one(user, "add_to_queue").enabled
    await user.should_not_see(marker="queue_status")


# --- the running job ------------------------------------------------------------------


async def test_panel_shows_the_running_job(service, tmp_path, user: User):
    add(service, tmp_path, "done", S.RUNNING, S.DONE)
    add(service, tmp_path, "running", S.RUNNING)
    add(service, tmp_path, "queued")
    service.progress = 0.62

    await open_page(user)

    for text in ("running.mp3", "Transcribing · Step 1 of 1 · CPU", "62%"):
        await user.should_see(text, retries=200)
    await user.should_see("Queue · 1 waiting · 1 done")
    await user.should_not_see(marker="job_running")  # in the header, not in the list
    await user.should_see(marker="stop_job")
    await user.should_see(marker="stop_all")  # the running and the queued job are open


async def test_pause_resume_and_finished_states(service, tmp_path, user: User):
    add(service, tmp_path, "queued")
    await open_page(user)
    await user.should_see("Paused · 1 waiting", retries=200)
    await user.should_not_see(marker="stop_job")
    assert one(user, "pause_queue").text == "Resume"
    user.find(marker="pause_queue").click()
    assert not service.paused
    user.find(marker="pause_queue").click()  # pause before yielding to the scheduler
    assert service.paused

    service.store.update("queued", status=S.CANCELLED)
    await user.should_see("All jobs finished", retries=20)
    await user.should_see(marker="queue_status")  # finished jobs stay listed


async def test_stop_all_shows_with_more_than_one_open_job(service, tmp_path, user: User):
    add(service, tmp_path, "a", S.RUNNING)
    await open_page(user)
    await user.should_see("a.mp3", retries=200)
    await user.should_not_see(marker="stop_all")
    add(service, tmp_path, "b")
    add(service, tmp_path, "c", S.FAILED)
    await user.should_see(marker="stop_all", retries=20)

    user.find(marker="stop_all").click()
    await user.should_see("Stop all 2 unfinished jobs?")
    user.find(marker="confirm_ok").click()
    await until(lambda: service.store.get("b")[1].status == S.CANCELLED)


# --- the list -------------------------------------------------------------------------


async def test_list_actions_per_status(service, tmp_path, user: User):
    add(service, tmp_path, "done", S.RUNNING, S.DONE)
    add(service, tmp_path, "failed", S.FAILED)
    add(service, tmp_path, "cancelled", S.CANCELLED)
    add(service, tmp_path, "first", language="de", speaker_detection=True, speaker_count=3)
    add(service, tmp_path, "last")

    await open_page(user)
    await user.should_see("Queue · 2 waiting · 1 done · 1 failed · 1 cancelled", retries=200)
    await user.should_see("large-v3-turbo · de · 3 speakers · CPU")

    def icons(job_id):
        icons = ("download", "replay", "arrow_upward", "arrow_downward", "close")
        return [icon for icon in icons if row_button(user, job_id, icon).elements]

    assert icons("done") == ["download", "close"]
    assert icons("failed") == ["replay", "close"]
    assert icons("cancelled") == ["replay", "close"]
    assert icons("first") == ["arrow_upward", "arrow_downward", "close"]
    enabled = {
        (job_id, icon): [b.enabled for b in row_button(user, job_id, icon).elements]
        for job_id in ("first", "last")
        for icon in ("arrow_upward", "arrow_downward")
    }
    assert enabled == {
        ("first", "arrow_upward"): [False],
        ("first", "arrow_downward"): [True],
        ("last", "arrow_upward"): [True],
        ("last", "arrow_downward"): [False],
    }


async def test_move_and_retry(service, tmp_path, user: User):
    add(service, tmp_path, "cancelled", S.CANCELLED)
    add(service, tmp_path, "a")
    add(service, tmp_path, "b")
    await open_page(user)
    await user.should_see("b.mp3", retries=200)

    row_button(user, "a", "arrow_downward").click()
    assert ids(service) == ["cancelled", "b", "a"]
    row_button(user, "cancelled", "replay").click()
    assert ids(service) == ["b", "a", "cancelled"]
    assert service.store.get("cancelled")[1].status == S.QUEUED


async def test_failed_job_shows_its_error(service, tmp_path, user: User):
    add(service, tmp_path, "a", S.FAILED)
    service.store.update("a", error="CUDA out of memory", traceback="Traceback …")
    await open_page(user)

    user.find("Failed ⓘ").click()
    await user.should_see("CUDA out of memory")
    user.find(kind=ui.button, content="Retry").click()
    await until(lambda: service.store.get("a")[1].status == S.QUEUED)


async def test_remove_asks_first(service, tmp_path, user: User):
    add(service, tmp_path, "x", S.FAILED)
    (service.store.work_dir("x") / "input").mkdir(parents=True)
    await open_page(user)
    await user.should_see("x.mp3", retries=200)

    row_button(user, "x", "close").click()
    await user.should_see("Remove x.mp3 from the queue?")
    await user.should_see("The uploaded file will be deleted.")
    user.find(marker="confirm_ok").click()
    await until(lambda: service.jobs() == [])


@pytest.mark.parametrize("action", ["close", "Clear finished"])
async def test_remove_confirmation_handles_a_missing_job(
    service, tmp_path, user: User, monkeypatch, action
):
    add(service, tmp_path, "x", S.FAILED)
    await open_page(user)

    def missing(job_id):
        raise KeyError(job_id)

    monkeypatch.setattr(service.store, "work_dir", missing)
    user.find(kind=ui.button, content=action).click()
    await user.should_see(
        "Remove x.mp3 from the queue?"
        if action == "close"
        else "Remove 1 finished, failed or cancelled job from the queue?"
    )
    await user.should_not_see("uploaded file")
    user.find("Back").click()


async def test_clear_finished_keeps_the_others(service, tmp_path, user: User):
    add(service, tmp_path, "a")
    add(service, tmp_path, "b", S.RUNNING, S.DONE)
    add(service, tmp_path, "c", S.CANCELLED)
    (service.store.work_dir("c") / "input").mkdir(parents=True)
    await open_page(user)

    user.find(kind=ui.button, content="Clear finished").click()
    await user.should_see("Remove 2 finished, failed or cancelled jobs from the queue?")
    await user.should_see("This also deletes the uploaded files of 1 failed or cancelled job.")
    user.find(marker="confirm_ok").click()

    await until(lambda: ids(service) == ["a"])


async def test_export_warning_is_shown(service, tmp_path, user: User):
    add(service, tmp_path, "a", S.RUNNING)
    await open_page(user)
    warning = "Copy to /media/usb/transcriptions failed: disk full"
    service.store.update("a", status=S.DONE, file_id="a-result", warnings=[warning])
    await user.should_see("Done with warnings", retries=20)
    user.find(kind=ui.button, content="Done with warnings").click()
    await user.should_see(warning)


async def test_add_to_queue_adds_one_job(service, tmp_path, user: User, monkeypatch):
    """The desktop window picks a path (Linux, Flatpak, macOS), so nothing is uploaded."""
    monkeypatch.setattr(app.native, "main_window", SimpleNamespace(signal_server_shutdown=print))
    monkeypatch.setattr(aTrain_core.globals, "LINUX", True)  # read when the page is built
    monkeypatch.setattr(file_component, "LINUX", True)
    await open_page(user)
    app.storage.general.update(CHEAP_SETTINGS)
    add_button = one(user, "add_to_queue")
    assert add_button.text == "Transcribe"
    (tmp_path / "one.mp3").write_bytes(b"audio")
    with user.client:
        (picker,) = ElementFilter(kind=file_component.CustomUpload)
    picker.selected_path = str(tmp_path / "one.mp3")

    user.find(marker="add_to_queue").click()

    await until(lambda: len(service.jobs()) == 1)
    ((spec, _),) = service.jobs()
    assert (spec.display_name, spec.source, spec.model) == ("one.mp3", tmp_path / "one.mp3", "tiny")
    await user.should_see("Queue · 1 waiting", retries=20)
    assert add_button.text == "Add to queue"


def test_a_cleared_cpu_threads_field_means_the_default(tmp_path):
    state = {**CHEAP_SETTINGS, "cpu_threads": None}
    spec = queue_ui.build_spec_from_state(
        state, job_id="a", source=tmp_path / "a.mp3", display_name="a.mp3"
    )
    assert spec.cpu_threads == 0

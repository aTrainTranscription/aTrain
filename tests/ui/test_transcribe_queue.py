"""The transcribe page with its queue panel and several-file input, with a real but paused
QueueService on a temporary store (it never starts a child)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
import pytest
from aTrain.components.settings import file as file_component
from aTrain.components.settings import model as model_component
from aTrain.utils import file_selection, flatpak_portal, queue_ui, transcription
from aTrain.utils.file_selection import FileSelection, check_dropped, ignored_files
from aTrain.utils.linux_drop import EVENT
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
        JobStore(tmp_path / "queue"), launch_phase1=no_child, launch_phase2=no_child
    )
    service.pause()
    await service.start()

    async def get_service():
        return service

    monkeypatch.setattr(queue_ui, "get_queue_service", get_service)
    yield service
    await service.stop()


@pytest.fixture
def selections(monkeypatch) -> list[FileSelection]:
    """The file selections of the pages opened in the test, newest last."""
    made = []

    class Recorded(FileSelection):
        def __init__(self, *args):
            super().__init__(*args)
            made.append(self)

    monkeypatch.setattr(file_component, "FileSelection", Recorded)
    return made


@pytest.fixture
def known_models(monkeypatch):
    """The model select lists `tiny` and `base`, whatever is downloaded on the host."""
    monkeypatch.setattr(model_component, "read_transcription_models", lambda: ["tiny", "base"])


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


# --- files and settings ---------------------------------------------------------------


async def test_add_to_queue_adds_one_job_per_file(
    service, known_models, selections, tmp_path, user: User
):
    await open_page(user)
    await user.should_not_see(marker="queue_status")
    await user.should_not_see("The queue is empty.")
    add_button = one(user, "add_to_queue")
    assert not add_button.enabled
    await user.should_see("Drop audio or video files")
    paths = []
    for name in ("one.mp3", "two.mp3"):
        (tmp_path / name).write_bytes(b"audio")
        paths.append(tmp_path / name)
    selection = selections[-1]
    selection.add_paths(paths)
    await user.should_see("2 files selected")
    assert add_button.enabled and add_button.text == "Transcribe 2 files"
    one(user, "select_speakers").set_value(2)

    user.find(marker="add_to_queue").click()

    await until(lambda: len(service.jobs()) == 2)
    jobs = service.jobs()
    assert [spec.display_name for spec, _ in jobs] == ["one.mp3", "two.mp3"]
    assert [spec.source for spec, _ in jobs] == paths  # picked files are used, not copied
    assert all(spec.model == "tiny" and spec.speaker_count == 2 for spec, _ in jobs)
    await user.should_see("Drop audio or video files")  # the selection is cleared
    assert not add_button.enabled and add_button.text == "Add to queue"
    await user.should_see("Queue · 2 waiting", retries=20)
    await user.should_see("two.mp3")


async def test_files_can_be_removed_from_the_selection(service, selections, tmp_path, user: User):
    await open_page(user)
    paths = [tmp_path / name for name in ("a.mp3", "b.mp3")]
    selection = selections[-1]
    selection.add_paths(paths)
    await user.should_see("2 files selected")
    with user.client:
        buttons = list(ElementFilter(kind=ui.button, content="close").within(marker="drop_zone"))
    UserInteraction(user, {buttons[0]}, None).click()  # the ✕ of a.mp3
    assert selection.names == ["b.mp3"]
    await user.should_see("1 file selected")
    user.find("Clear").click()
    assert selection.names == []
    assert not one(user, "add_to_queue").enabled


async def test_a_folder_offers_a_copy_next_to_the_files(service, selections, tmp_path, user: User):
    await open_page(user)
    folder = tmp_path / "recordings"
    folder.mkdir()
    for name in ("a.mp3", "notes.txt"):
        (folder / name).write_text("x")
    selection = selections[-1]
    selection.ignored = ignored_files(folder, [folder / "a.mp3"])  # as the folder picker does
    selection.add_paths([folder / "a.mp3"], folder)

    await user.should_see("1 other file in the folder ignored")
    user.find("Also save a copy next to the source files").click()
    assert selection.export_dir == folder / "transcriptions"
    selection.add_paths([tmp_path / "b.mp3"])  # more files: no folder any more
    assert selection.export_dir is None


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
    (service.store.uploads_root / "x").mkdir(parents=True)
    await open_page(user)
    await user.should_see("x.mp3", retries=200)

    row_button(user, "x", "close").click()
    await user.should_see("Remove x.mp3 from the queue?")
    await user.should_see("The uploaded file will be deleted.")
    user.find(marker="confirm_ok").click()
    await until(lambda: service.jobs() == [])


async def test_clear_finished_keeps_the_others(service, tmp_path, user: User):
    add(service, tmp_path, "a")
    add(service, tmp_path, "b", S.RUNNING, S.DONE)
    add(service, tmp_path, "c", S.CANCELLED)
    (service.store.uploads_root / "c").mkdir(parents=True)
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


# --- adding files (the code behind the page) ------------------------------------------


def test_check_dropped(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    for path in (tmp_path / "a.mp3", tmp_path / "notes.txt", folder / "b.wav"):
        path.write_bytes(b"x")

    files, unreadable, unsupported = check_dropped(
        [tmp_path / "a.mp3", tmp_path / "notes.txt", folder, tmp_path / "gone.mp3"]
    )

    assert files == [tmp_path / "a.mp3", folder / "b.wav"]
    assert unreadable == [tmp_path / "gone.mp3"]  # e.g. outside a Flatpak's sandbox
    assert unsupported == ["notes.txt"]


def drop(user: User, paths) -> None:
    """What the Linux window process sends for a drop (aTrain.utils.linux_drop)."""
    UserInteraction(user, {user.client.layout}, None).trigger(EVENT, [str(p) for p in paths])


@pytest.fixture
def desktop(monkeypatch):
    """A native window on Linux, where drops come from the window process."""
    window = SimpleNamespace(signal_server_shutdown=lambda: None)
    monkeypatch.setattr(app.native, "main_window", window)
    monkeypatch.setattr(file_component, "LINUX", True)


async def test_dropped_files_are_added_in_the_desktop_app(
    service, desktop, selections, tmp_path, user: User
):
    for name in ("a.mp3", "b.mp3"):
        (tmp_path / name).write_bytes(b"audio")
    await open_page(user)

    drop(user, [tmp_path / "a.mp3", tmp_path / "b.mp3", Path("/gone.mp3")])

    expected = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    await until(lambda: selections[-1].paths == expected)
    await user.should_see("2 files selected")
    await user.should_see("aTrain can't open gone.mp3.")


async def test_an_unreadable_drop_in_a_flatpak_opens_the_chooser_there(
    service, desktop, selections, tmp_path, user: User, monkeypatch
):
    calls = []
    granted = tmp_path / "doc" / "a.mp3"

    def pick_native(directory, folder=None):
        calls.append((directory, folder))
        return [str(granted)]

    monkeypatch.setattr(file_selection, "FLATPAK", True)
    monkeypatch.setattr(flatpak_portal, "pick_native", pick_native)
    await open_page(user)

    drop(user, [Path("/home/me/Downloads/a.mp3")])  # a drag without the portal

    await user.should_see("Select a.mp3 to give aTrain access to it.")
    await until(lambda: selections[-1].paths == [granted])
    assert calls == [(False, Path("/home/me/Downloads"))]


async def test_drops_are_ignored_in_a_browser(service, selections, tmp_path, user: User):
    (tmp_path / "a.mp3").write_bytes(b"audio")
    await open_page(user)

    drop(user, [tmp_path / "a.mp3"])

    assert selections[-1].names == []  # paths on the browser's computer


async def test_selection_stays_when_the_jobs_cant_be_added(
    service, selections, tmp_path, user: User, monkeypatch
):
    await open_page(user)
    app.storage.general.update({**CHEAP_SETTINGS, "model": None})  # no model downloaded yet
    errors = []
    monkeypatch.setattr(transcription, "dialog_error", lambda **kw: errors.append(kw))
    (tmp_path / "a.mp3").write_bytes(b"audio")
    selection = selections[-1]
    selection.add_paths([tmp_path / "a.mp3"])

    with user:
        await selection.submit()

    assert "Model None is not available" in errors[0]["error"]
    assert selection.paths == [tmp_path / "a.mp3"] and service.jobs() == []


def test_a_cleared_cpu_threads_field_means_the_default(tmp_path):
    state = {**CHEAP_SETTINGS, "cpu_threads": None}
    spec = queue_ui.build_spec_from_state(
        state, job_id="a", source=tmp_path / "a.mp3", display_name="a.mp3"
    )
    assert spec.cpu_threads == 0


async def test_the_desktop_window_picks_paths(service, selections, tmp_path, user, monkeypatch):
    """Windows and macOS: the window's own dialog gives paths, so nothing is uploaded."""
    monkeypatch.setattr(app.native, "main_window", SimpleNamespace(signal_server_shutdown=print))
    monkeypatch.setattr(file_component, "LINUX", False)
    monkeypatch.setattr(file_component, "FLATPAK", False)

    async def pick_in_window(folder):
        return [str(tmp_path / "a.mp3")]

    monkeypatch.setattr(file_selection, "pick_in_window", pick_in_window)
    await open_page(user)

    with user:
        await selections[-1].browse_files()

    assert selections[-1].paths == [tmp_path / "a.mp3"]
    assert not any(service.store.uploads_root.glob("*"))


async def test_browser_files_are_uploaded_when_added(service, selections, user: User):
    await open_page(user)
    app.storage.general.update(CHEAP_SETTINGS)
    selection = selections[-1]
    files = [ui.upload.SmallFileUpload(name, "audio/mpeg", b"audio") for name in "abc"]

    with user:
        await selection.uploaded(SimpleNamespace(files=files))
    staged = list(selection.paths)
    selection.remove(0)  # deletes its uploaded copy
    assert not staged[0].parent.exists()
    with user:
        await selection.submit()

    jobs = service.jobs()
    assert [spec.display_name for spec, _ in jobs] == ["b", "c"]
    assert [spec.source for spec, _ in jobs] == staged[1:]
    assert all(spec.source.parent.name == spec.id for spec, _ in jobs)  # removed with the job
    assert selection.paths == [] and selection.uploads == set()

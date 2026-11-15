"""Full UI E2E via NiceGUI's in-process User fixture (no browser).

Renders the real transcription page and drives a transcription through the
upload staging and queue APIs (stage_upload -> start_paths -> phase children
-> "Done" in the queue list), with the tiny model on CPU. Upload-handler and
button wiring are covered separately in test_transcribe_queue.py.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
from aTrain.utils import queue_ui
from aTrain.utils.transcription import stage_upload, start_paths
from aTrain_core.load_resources import get_model
from nicegui import app, events, ui
from nicegui.testing import User

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"


async def test_main_page_renders(user: User):
    await user.open("/")
    await user.should_see(kind=ui.button, content="Transcribe", retries=100)


CHEAP_SETTINGS = {
    "model": "tiny",
    "language": "auto-detect",
    "speaker_detection": True,  # so the job runs through both phase children
    "speaker_count": 0,
    "GPU": False,
    "compute_type": "int8",
    "temperature_override": None,
    "initial_prompt": None,
    "cpu_threads": 0,
}


async def test_transcribe_through_ui(user: User):
    """Stage a browser upload and run it through the real queue to the rendered result."""
    get_model("tiny")  # a fresh machine (CI) has no model, and the job would be refused
    await user.open("/")
    # The UI settings components write into app.storage.general; set them
    # directly to force the cheap path (tiny model, CPU) over the UI default.
    app.storage.general.update(CHEAP_SETTINGS)
    # stage_upload is exactly what the upload handler calls. Build a *real*
    # MultiUploadEventArguments rather than a stand-in: a hand-rolled double
    # freezes whatever attribute names NiceGUI happened to use when it was
    # written, so an upload-API change (2.x `.name`/`.content` -> 3.x `.file`)
    # slips through green. sender/client are unused by the handler.
    upload_event = events.MultiUploadEventArguments(
        sender=cast(object, None),  # type: ignore[arg-type]
        client=cast(object, None),  # type: ignore[arg-type]
        files=[
            ui.upload.SmallFileUpload(
                name="sample_short.mp3",
                content_type="audio/mpeg",
                _data=FIXTURE.read_bytes(),
            )
        ],
    )
    with user:
        assert await start_paths([await stage_upload(file) for file in upload_event.files])
    await user.open("/")
    await user.should_see("Done", retries=600)


async def test_large_upload_is_staged_from_disk(tmp_path, monkeypatch):
    """The streaming branch, which is the normal one for real recordings.

    NiceGUI hands over a `LargeFileUpload` (a temp file it streamed to) rather
    than a `SmallFileUpload` (whole file in a bytes buffer) once an upload
    exceeds `MultiPartParser.spool_max_size` - 1 MB by starlette's default,
    which every audio file clears. Without this the tests would only ever cover
    the in-memory branch.
    """
    source = tmp_path / "upload.tmp"
    source.write_bytes(FIXTURE.read_bytes())
    store = SimpleNamespace(uploads_root=tmp_path / "uploads")

    async def service():
        return SimpleNamespace(store=store)

    monkeypatch.setattr(queue_ui, "get_queue_service", service)

    staged = await stage_upload(
        ui.upload.LargeFileUpload(name="recording.mp3", content_type="audio/mpeg", _path=source)
    )

    assert staged.read_bytes() == FIXTURE.read_bytes()
    assert staged.name == "recording.mp3" and staged.parent.parent == store.uploads_root

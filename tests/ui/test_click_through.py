"""Full UI E2E via NiceGUI's in-process User fixture (no browser).

Renders the real transcription page and drives a transcription through the
app's real wiring (start_transcription -> run.cpu_bound -> finished dialog),
with the tiny model on CPU. Complements the lighter boot-serve smoke.
"""

from pathlib import Path
from typing import cast

import aTrain_core.transcribe  # noqa: F401  pre-import so the splash import is instant
from aTrain.utils import transcription
from aTrain.utils.transcription import start_transcription, start_transcription_from_path
from nicegui import app, events, ui
from nicegui.testing import User

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"


async def test_main_page_renders(user: User):
    await user.open("/")
    await user.should_see("Start", retries=100)


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


async def test_transcribe_through_ui(user: User):
    """Browser-upload path (Windows/macOS): NiceGUI hands us an upload event."""
    await user.open("/")
    # The UI settings components write into app.storage.general; set them
    # directly to force the cheap path (tiny model, CPU) over the UI default.
    app.storage.general.update(CHEAP_SETTINGS)
    # start_transcription is exactly what the upload handler calls. Build a
    # *real* UploadEventArguments rather than a stand-in: a hand-rolled double
    # freezes whatever attribute names NiceGUI happened to use when it was
    # written, so an upload-API change (2.x `.name`/`.content` -> 3.x `.file`)
    # slips through green. sender/client are unused by the handler.
    upload_event = events.UploadEventArguments(
        sender=cast(object, None),  # type: ignore[arg-type]
        client=cast(object, None),  # type: ignore[arg-type]
        file=ui.upload.SmallFileUpload(
            name="sample_short.mp3",
            content_type="audio/mpeg",
            _data=FIXTURE.read_bytes(),
        ),
    )
    with user:
        await start_transcription(upload_event)
    await user.should_see("transcribed your file", retries=600)


async def test_large_upload_is_staged_from_disk(tmp_path):
    """The streaming branch, which is the normal one for real recordings.

    NiceGUI hands over a `LargeFileUpload` (a temp file it streamed to) rather
    than a `SmallFileUpload` (whole file in a bytes buffer) once an upload
    exceeds `MultiPartParser.spool_max_size` - 1 MB by starlette's default,
    which every audio file clears. Without this the tests would only ever cover
    the in-memory branch.
    """
    source = tmp_path / "upload.tmp"
    source.write_bytes(FIXTURE.read_bytes())
    payload = transcription.UploadPayload(
        name="recording.mp3",
        upload=ui.upload.LargeFileUpload(
            name="recording.mp3", content_type="audio/mpeg", _path=source
        ),
    )

    staged = await payload.materialise(tmp_path / "staging", "recording.mp3")

    assert staged.read_bytes() == FIXTURE.read_bytes()
    assert staged != source


async def test_picked_path_reaches_the_pipeline_unchanged(monkeypatch):
    """Native-picker path (Linux/Flatpak): the Start button hands us a path.

    This second entry point bypasses NiceGUI's upload entirely. CI runs on
    Linux, where `transcribe.py` wires *only* this branch - so without a test
    here the picker adapter is unexercised on Windows and the upload adapter
    is unexercised on CI, and a mismatched payload breaks whichever platform
    nobody happened to run.

    Only the adapter is checked: everything downstream of `run_pipeline`
    is the same code the upload test already drives end to end, and a second
    real transcription would double the `e2e (app)` job for no added coverage.
    """
    captured: list[transcription.UploadPayload] = []

    async def capture(payload: transcription.UploadPayload) -> None:
        captured.append(payload)

    monkeypatch.setattr(transcription, "run_pipeline", capture)
    await start_transcription_from_path(FIXTURE, FIXTURE.name)

    (payload,) = captured
    assert payload.name == FIXTURE.name
    assert payload.path == FIXTURE
    assert payload.upload is None
    # A file the picker already gave us must be handed on as-is, not copied
    # into the staging directory.
    assert await payload.materialise(Path("unused"), "unused.mp3") == FIXTURE

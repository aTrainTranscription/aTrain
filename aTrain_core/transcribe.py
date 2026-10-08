import os
import warnings
from datetime import datetime
from functools import partial
from multiprocessing import Manager, Process
from multiprocessing.managers import DictProxy
from pathlib import Path

import numpy as np

# pyannote imports can emit a non-actionable torchcodec warning in our runtime;
# keep this narrow to that single message and module.
warnings.filterwarnings(
    "ignore",
    message=r"(?s).*torchcodec is not installed correctly so built-in audio decoding will fail.*",
    category=UserWarning,
    module=r"pyannote\.audio\.core\.io",
)

# engine.py imports these lazily; they are imported here too because the splash
# screen imports this module to have them loaded before the first transcription.
import faster_whisper  # noqa: F401
import pyannote.audio  # noqa: F401
from werkzeug.utils import secure_filename

from aTrain_core import engine
from aTrain_core.engine import transcription_with_progress_bar  # noqa: F401  public name
from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.load_resources import get_model
from aTrain_core.outputs import (
    claim_file_id,
    create_metadata,
    write_final_outputs,
    write_logfile,
)
from aTrain_core.settings import Device, ModelKey, Settings


def prepare_transcription(file: Path) -> tuple[Path, str, str]:
    """Create timestamp, file_id and directory for transcription"""

    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    file = file.with_name(secure_filename(file.name))
    file_id = claim_file_id(file, timestamp)
    write_logfile(f"File ID created: {file_id}", file_id)
    return file, file_id, timestamp


def transcribe(settings: Settings):
    """Transcribes audio file with specified parameters."""

    backend = engine.backend_of(settings.model)
    write_logfile("Directory created", settings.file_id)
    audio_array, audio_duration = load_audio(settings)
    create_metadata(settings, audio_duration)
    model_path = get_model(settings.model)
    write_logfile("Model loaded", settings.file_id)
    if settings.device == Device.GPU or backend == "crisper-transformers":
        write_logfile("Transcribing in seperate process", settings.file_id)
        transcript = run_transcription_in_process(settings, model_path, audio_array)
    elif settings.device == Device.CPU:
        write_logfile("Transcribing in same process", settings.file_id)
        transcript = run_transcription(settings, model_path, audio_array)
    if settings.speaker_detection and transcript:
        transcript = run_speaker_detection(settings, audio_duration, audio_array, transcript)
    write_final_outputs(settings, transcript, audio_duration=audio_duration, backend=backend)


def load_audio(settings: Settings) -> tuple[np.ndarray, int]:
    """Load the audio and calculate audio duration"""
    return engine.decode(settings.file, partial(write_logfile, file_id=settings.file_id))


def run_transcription(
    settings: Settings,
    model_path: Path,
    audio_array: np.ndarray,
    returnDict: DictProxy | dict = {},
) -> dict | None:
    """Run a transcription through the backend selected by the model config."""
    backend = None
    try:
        backend = engine.backend_of(settings.model)
        key = ModelKey(settings.model, settings.device, settings.compute_type, settings.cpu_threads)
        transcriber = engine.load_transcriber(key, model_path)
        transcript = transcriber.transcribe(
            audio_array,
            language=settings.language,
            initial_prompt=settings.initial_prompt,
            temperature=settings.temperature,
            progress=settings.progress,
            log=partial(write_logfile, file_id=settings.file_id),
        )
        write_logfile("Transcription successful", settings.file_id)
        if settings.device == Device.GPU or backend == "crisper-transformers":
            returnDict["transcript"] = transcript
        if settings.device == Device.CPU:
            return transcript
        os._exit(0)

    except Exception as error:
        if settings.device == Device.CPU and backend != "crisper-transformers":
            raise error
        returnDict["error"] = error


def run_transcription_in_process(
    settings: Settings, model_path: Path, audio_array: np.ndarray
) -> dict:
    """Run a transcription in a seperate process.
    This is a workaround to deal with a termination issue: https://github.com/guillaumekln/faster-whisper/issues/71"""
    with Manager() as manager:
        returnDict = manager.dict()
        p = Process(
            target=run_transcription,
            kwargs={
                "settings": settings,
                "model_path": model_path,
                "audio_array": audio_array,
                "returnDict": returnDict,
            },
            daemon=True,
        )
        p.start()
        p.join()
        p.close()

        if "error" in returnDict.keys():
            error: Exception = returnDict["error"]
            raise error
        transcript = returnDict["transcript"]
        return transcript


def run_speaker_detection(
    settings: Settings, audio_duration: int, audio_array: np.ndarray, transcript: dict
) -> dict:
    """Run speaker detection using a pyannote.audio model"""
    log = partial(write_logfile, file_id=settings.file_id)
    pipeline = engine.load_diarizer(settings.device, log)
    return engine.diarize(
        pipeline,
        audio_array,
        transcript,
        speaker_count=settings.speaker_count,
        progress=settings.progress,
        log=log,
    )

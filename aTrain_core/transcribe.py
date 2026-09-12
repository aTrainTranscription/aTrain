import os
import sys
import warnings
from datetime import datetime
from multiprocessing import Manager, Process
from multiprocessing.managers import DictProxy
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

# pyannote imports can emit a non-actionable torchcodec warning in our runtime;
# keep this narrow to that single message and module.
warnings.filterwarnings(
    "ignore",
    message=r"(?s).*torchcodec is not installed correctly so built-in audio decoding will fail.*",
    category=UserWarning,
    module=r"pyannote\.audio\.core\.io",
)

from pyannote.audio import Pipeline
from pyannote.audio.pipelines.speaker_diarization import DiarizeOutput
from pyannote.audio.pipelines.utils.hook import ProgressHook
from tqdm import tqdm
from werkzeug.utils import secure_filename

from aTrain_core.globals import SAMPLING_RATE, TIMESTAMP_FORMAT
from aTrain_core.load_resources import get_model, load_model_config_file
from aTrain_core.outputs import (
    add_processing_time_to_metadata,
    assign_word_speakers,
    create_directory,
    create_file_id,
    create_metadata,
    create_output_files,
    named_tuple_to_dict,
    transform_speakers_results,
    write_logfile,
)
from aTrain_core.settings import Device, Settings


class CustomProgressHook(ProgressHook):
    """A custom progress hook that updates the GUI and prints progress information during processing."""

    def __init__(self, progress: DictProxy | dict):
        super().__init__()
        self._progress = progress

    def __call__(self, step_name, step_artifact, file=None, total=None, completed=None):
        super().__call__(step_name, step_artifact, file, total, completed)
        self._progress["task"] = "Detect Speakers"
        if step_name == "segmentation" and total and completed:
            self.grand_total = total * 2
            self._progress["total"] = self.grand_total
            self._progress["current"] = completed
        elif step_name == "embeddings" and total and completed:
            self._progress["current"] = (completed / total + 1) * self.grand_total / 2


def prepare_transcription(file: Path) -> tuple[Path, str, str]:
    """Create timestamp, file_id and directory for transcription"""

    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    file = file.with_name(secure_filename(file.name))
    file_id = create_file_id(file, timestamp)
    create_directory(file_id)
    write_logfile(f"File ID created: {file_id}", file_id)
    return file, file_id, timestamp


def transcribe(settings: Settings):
    """Transcribes audio file with specified parameters."""

    write_logfile("Directory created", settings.file_id)
    audio_array, audio_duration = load_audio(settings)
    create_metadata(settings, audio_duration)
    model_path = get_model(settings.model)
    write_logfile("Model loaded", settings.file_id)
    if settings.device == Device.GPU:
        write_logfile("Transcribing in seperate process", settings.file_id)
        transcript = run_transcription_in_process(settings, model_path, audio_array)
    elif settings.device == Device.CPU:
        write_logfile("Transcribing in same process", settings.file_id)
        transcript = run_transcription(settings, model_path, audio_array)
    if settings.speaker_detection and transcript:
        transcript = run_speaker_detection(settings, audio_duration, audio_array, transcript)
    create_output_files(transcript, settings.speaker_detection, settings.file_id)
    write_logfile("No speaker detection. Created output files", settings.file_id)
    add_processing_time_to_metadata(settings.file_id)
    write_logfile("Processing time added to metadata", settings.file_id)


def load_audio(settings: Settings) -> tuple[np.ndarray, int]:
    """Load the audio and calculate audio duration"""
    try:
        if isinstance(settings.file, Path):
            file = settings.file.as_posix()
        else:
            file = settings.file
        audio_array = decode_audio(file, sampling_rate=SAMPLING_RATE)
    except Exception as e:
        write_logfile(f"File or path invalid: {e}", settings.file_id)
        raise Exception("""Check file & path: File either has no audio or the name of the file path or file includes spaces.
                        Please remove or exchange them with underscores.""")
    write_logfile("Audio file loaded and decoded", settings.file_id)
    audio_duration = int(len(audio_array) / SAMPLING_RATE)
    write_logfile("Audio duration calculated", settings.file_id)
    return audio_array, audio_duration


def run_transcription(
    settings: Settings,
    model_path: Path,
    audio_array: np.ndarray,
    returnDict: DictProxy | dict = {},
) -> dict | None:
    """Run a transcription using a whisper model."""
    try:
        whisper_model = WhisperModel(
            model_size_or_path=model_path.as_posix(),
            device="cuda" if settings.device == Device.GPU else "cpu",
            compute_type=settings.compute_type.value,
            cpu_threads=settings.cpu_threads,
        )
        model_type = load_model_config_file()[settings.model]["type"]
        write_logfile(f"Transcribing with {model_type} model.", settings.file_id)

        segments, info = whisper_model.transcribe(
            audio=audio_array,
            vad_filter=True,
            beam_size=5,
            word_timestamps=True,
            language=None if settings.language == "auto-detect" else settings.language,
            max_new_tokens=None if model_type == "distil" else 128,
            no_speech_threshold=0.6,
            condition_on_previous_text=False if model_type == "distil" else True,
            initial_prompt=settings.initial_prompt,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            if settings.temperature is None
            else settings.temperature,
        )
        segments = transcription_with_progress_bar(segments, info, settings.progress)
        transcript = {"segments": [named_tuple_to_dict(s) for s in segments]}
        write_logfile("Transcription successful", settings.file_id)
        if settings.device == Device.CPU:
            return transcript
        if settings.device == Device.GPU:
            returnDict["transcript"] = transcript
            os._exit(0)

    except Exception as error:
        if settings.device == Device.CPU:
            raise error
        if settings.device == Device.GPU:
            returnDict["error"] = error


def transcription_with_progress_bar(segments, info, progress: DictProxy | dict):
    """Transcribes audio segments with progress bar."""
    total_duration = round(info.duration, 2)
    timestamps = 0.0  # to get the current segments
    segments_new = []

    # Using NullWriter as workaround for https://github.com/tqdm/tqdm/issues/794
    class NullWriter:
        def write(self, data): ...

    sys.stdout = sys.stdout or NullWriter()
    sys.stderr = sys.stderr or NullWriter()

    with tqdm(
        total=total_duration, unit=" audio seconds", desc="Transcribing with Whisper"
    ) as pbar:
        progress["task"] = "Transcribe"
        for segment in segments:
            segments_new.append(segment)
            progress["current"] = segment.end
            progress["total"] = total_duration
            pbar.update(segment.end - timestamps)
            timestamps = segment.end
        if timestamps < info.duration:  # silence at the end of the audio
            pbar.update(info.duration - timestamps)

    return segments_new


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
    import torch

    model_path = get_model("speaker-detection")
    write_logfile("Speaker detection model loaded", settings.file_id)
    audio = {
        "waveform": torch.from_numpy(audio_array[None, :]),
        "sample_rate": SAMPLING_RATE,
    }
    pipeline = Pipeline.from_pretrained(model_path)
    if not pipeline:
        raise Exception("Failed to initialize speaker detection pipeline!")
    write_logfile("Detecting speakers", settings.file_id)

    if settings.device == Device.GPU:
        pipeline.to(torch.device("cuda"))

    with CustomProgressHook(settings.progress) as hook:
        output: DiarizeOutput = pipeline(audio, num_speakers=settings.speaker_count, hook=hook)
    segments = output.speaker_diarization
    speaker_results = transform_speakers_results(segments)
    write_logfile("Transformed diarization segments", settings.file_id)
    transcript_with_speaker = assign_word_speakers(speaker_results, transcript)
    write_logfile("Assigned speakers to words", settings.file_id)
    return transcript_with_speaker

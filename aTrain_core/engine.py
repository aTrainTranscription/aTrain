"""Backend-neutral transcription steps: load a model once, then transcribe or diarize
several recordings with it.

torch, faster_whisper, pyannote and crisperwhisper are imported inside functions, so this
module stays cheap to import (for example in a freshly spawned child process).
"""

import gc
import sys
import warnings
from collections.abc import Callable, MutableMapping
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, Protocol

import numpy as np
from tqdm import tqdm

from aTrain_core.backends.common import words_to_segments
from aTrain_core.globals import SAMPLING_RATE
from aTrain_core.load_resources import get_model, load_model_config_file
from aTrain_core.outputs import (
    assign_word_speakers,
    smooth_speaker_flips,
    transform_speakers_results,
)
from aTrain_core.settings import Device, ModelKey

Log = Callable[[str], None]

# pyannote imports can emit a non-actionable torchcodec warning in our runtime;
# keep this narrow to that single message and module.
warnings.filterwarnings(
    "ignore",
    message=r"(?s).*torchcodec is not installed correctly so built-in audio decoding will fail.*",
    category=UserWarning,
    module=r"pyannote\.audio\.core\.io",
)


class Transcriber(Protocol):
    backend: str

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str,
        initial_prompt: str | None,
        temperature: float | None,
        progress: MutableMapping,
        log: Log,
    ) -> dict: ...  # {"segments": [...]}, one segment per word

    def close(self) -> None: ...


class FasterWhisperTranscriber:
    backend = "faster-whisper"

    def __init__(self, key: ModelKey, model_path: Path):
        from faster_whisper import WhisperModel

        self._model_type = load_model_config_file()[key.model]["type"]
        self._model = WhisperModel(
            model_size_or_path=model_path.as_posix(),
            device="cuda" if key.device == Device.GPU else "cpu",
            compute_type=key.compute_type.value,
            cpu_threads=key.cpu_threads,
        )

    def transcribe(self, audio, *, language, initial_prompt, temperature, progress, log) -> dict:
        log(f"Transcribing with {self._model_type} model.")
        segments, info = self._model.transcribe(
            audio=audio,
            vad_filter=True,
            beam_size=5,
            word_timestamps=True,
            language=None if language == "auto-detect" else language,
            no_speech_threshold=0.6,
            condition_on_previous_text=self._model_type != "distil",
            initial_prompt=initial_prompt,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0] if temperature is None else temperature,
        )
        segments = transcription_with_progress_bar(segments, info, progress)
        words = []
        for segment in segments:
            if segment.words:
                words.extend(segment.words)
            elif segment.text.strip():
                log(f"Segment without word timestamps kept as one word: {segment.start:.1f}s")
                words.append({"word": segment.text, "start": segment.start, "end": segment.end})
        return {"segments": words_to_segments(words)}

    def close(self) -> None:
        self._model = None


class CrisperTranscriber:
    backend = "crisper-transformers"

    def __init__(self, key: ModelKey, model_path: Path):
        from aTrain_core.backends import crisper_transformers

        self._backend = crisper_transformers
        self._model = crisper_transformers.load_model(
            model_path, key.device, key.compute_type, key.cpu_threads
        )

    def transcribe(self, audio, *, language, initial_prompt, temperature, progress, log) -> dict:
        log("Transcribing with CrisperWhisper in verbatim mode.")
        return self._backend.transcribe_with_model(
            self._model,
            audio,
            language=language,
            initial_prompt=initial_prompt,
            temperature=temperature,
            progress=progress,
            log=log,
        )

    def close(self) -> None:
        self._model = None


class Qwen3Transcriber:
    backend = "qwen3-transformers"

    def __init__(self, key: ModelKey, model_path: Path):
        self._key = key
        self._model_path = model_path

    def transcribe(self, audio, *, language, initial_prompt, temperature, progress, log) -> dict:
        from aTrain_core.backends import qwen3_transformers

        log("Transcribing with Qwen3 ASR and word alignment.")
        # qwen3_transformers.transcribe still loads its models per call and reads a Settings.
        settings = SimpleNamespace(
            **asdict(self._key),
            language=language,
            initial_prompt=initial_prompt,
            temperature=temperature,
            progress=progress,
        )
        return qwen3_transformers.transcribe(settings, self._model_path, audio)

    def close(self) -> None:
        pass


TRANSCRIBERS: dict[str, type[FasterWhisperTranscriber | CrisperTranscriber | Qwen3Transcriber]] = {
    FasterWhisperTranscriber.backend: FasterWhisperTranscriber,
    CrisperTranscriber.backend: CrisperTranscriber,
    Qwen3Transcriber.backend: Qwen3Transcriber,
}


def backend_of(model: str) -> str:
    return load_model_config_file()[model]["backend"]


def load_transcriber(key: ModelKey, model_path: Path | None = None) -> Transcriber:
    """Load the Whisper model for key with the backend models.json names for it."""
    backend = backend_of(key.model)
    if backend not in TRANSCRIBERS:
        raise ValueError(f"Unsupported transcription backend: {backend}")
    return TRANSCRIBERS[backend](key, model_path or get_model(key.model))


def transcription_with_progress_bar(segments, info, progress: MutableMapping):
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


def decode(source: Path | BinaryIO, log: Log = print) -> tuple[np.ndarray, int]:
    """Decode a recording to 16 kHz mono and return it with its duration in seconds."""
    from faster_whisper.audio import decode_audio

    try:
        audio = decode_audio(
            source.as_posix() if isinstance(source, Path) else source, sampling_rate=SAMPLING_RATE
        )
    except Exception as e:
        log(f"File or path invalid: {e}")
        raise Exception("""Check file & path: File either has no audio or the name of the file path or file includes spaces.
                        Please remove or exchange them with underscores.""") from e
    log("Audio file loaded and decoded")
    audio_duration = int(len(audio) / SAMPLING_RATE)
    log("Audio duration calculated")
    return audio, audio_duration


def load_diarizer(device: Device, log: Log = print):
    """Load the pyannote speaker detection pipeline once."""
    import torch
    from pyannote.audio import Pipeline

    model_path = get_model("speaker-detection")
    log("Speaker detection model loaded")
    pipeline = Pipeline.from_pretrained(model_path)
    if not pipeline:
        raise Exception("Failed to initialize speaker detection pipeline!")
    if device == Device.GPU:
        pipeline.to(torch.device("cuda"))
    return pipeline


def diarize(
    pipeline,
    audio: np.ndarray,
    transcript: dict,
    *,
    speaker_count: int | None,
    progress: MutableMapping,
    log: Log = print,
) -> dict:
    """Detect speakers and label every word of the transcript with one of them."""
    import torch

    log("Detecting speakers")
    waveform = {"waveform": torch.from_numpy(audio[None, :]), "sample_rate": SAMPLING_RATE}
    with _progress_hook(progress) as hook:
        output = pipeline(waveform, num_speakers=speaker_count, hook=hook)
    speaker_results = transform_speakers_results(output.speaker_diarization)
    log("Transformed diarization segments")
    transcript_with_speaker = assign_word_speakers(speaker_results, transcript)
    smooth_speaker_flips(transcript_with_speaker["segments"])
    log("Assigned speakers to words")
    return transcript_with_speaker


def _progress_hook(progress: MutableMapping):
    """A pyannote progress hook that also updates aTrain's progress mapping."""
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    class CustomProgressHook(ProgressHook):
        def __init__(self, progress: MutableMapping):
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

    return CustomProgressHook(progress)


def release_memory(device: Device) -> None:
    """Free memory of models that are no longer referenced."""
    gc.collect()
    if device == Device.GPU:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

"""CrisperWhisper v2 adapter using its Transformers runtime."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from functools import partial, wraps
from pathlib import Path

from aTrain_core.backends.common import crisper_compute_type, words_to_segments
from aTrain_core.globals import SAMPLING_RATE
from aTrain_core.outputs import write_logfile
from aTrain_core.settings import ComputeType, Device, Settings


def _suppress_encoder_attentions(model) -> None:
    """Avoid retaining Whisper encoder self-attention during generation.

    Crisper's Transformers engine requests attention outputs so it can retain
    decoder cross-attention for word timing.  Transformers also returns the
    much larger encoder self-attention tensors, which Crisper does not use.
    Limit this change to the Crisper model's encoder; decoder cross-attention
    remains enabled for word timestamps.
    """
    encoder = model._engine.model.get_encoder()
    if getattr(encoder, "_atrain_encoder_attentions_suppressed", False):
        return

    original_forward = encoder.forward

    @wraps(original_forward)
    def forward(*args, **kwargs):
        kwargs["output_attentions"] = False
        return original_forward(*args, **kwargs)

    encoder.forward = forward
    encoder._atrain_encoder_attentions_suppressed = True


def load_model(model_path: Path, device: Device, compute_type: ComputeType, cpu_threads: int):
    """Load CrisperWhisper once, so several recordings can be transcribed with it."""
    # Import lazily so the normal faster-whisper path neither initializes nor
    # requires the Transformers backend at module import time.
    from crisperwhisper import CrisperWhisperModel

    # Transformers inference on CPU does not support float16. Crisper's
    # Transformers path also does not expose faster-whisper's int8 setting.
    model = CrisperWhisperModel(
        model_path.as_posix(),
        backend="transformers",
        device="cuda" if device == Device.GPU else "cpu",
        compute_type=crisper_compute_type(device, compute_type),
    )
    _suppress_encoder_attentions(model)
    if device == Device.CPU and cpu_threads:
        import torch

        torch.set_num_threads(cpu_threads)
    return model


def transcribe_with_model(
    model,
    audio,
    *,
    language: str,
    initial_prompt: str | None,
    temperature: float | None,
    progress: MutableMapping,
    log: Callable[[str], None],
) -> dict:
    """Run CrisperWhisper in verbatim mode and normalize its word timestamps."""
    if language == "auto-detect":
        raise ValueError("CrisperWhisper requires a language; select one instead of auto-detect.")
    if initial_prompt:
        log("CrisperWhisper does not support initial prompts; ignoring the setting.")
    if temperature is not None:
        log("CrisperWhisper does not support temperature; ignoring the setting.")

    progress["task"] = "Transcribe"
    progress["current"] = 0
    progress["total"] = 1
    result = model.transcribe(
        audio,
        sr=SAMPLING_RATE,
        language=language,
        mode="verbatim",
        word_timestamps=True,
        # CrisperWhisper 2.0.2 imports its CTranslate2-specific hallucination
        # helpers on the default path. Keep the Transformers backend usable
        # alongside faster-whisper's upstream ctranslate2 package.
        hallucination_mitigation=False,
        temperature_fallback=False,
    )
    words = result.words or []
    if result.words is None and result.text.strip():
        raise RuntimeError("CrisperWhisper returned no word timestamps.")
    progress["current"] = 1
    return {"segments": words_to_segments(words)}


def transcribe(settings: Settings, model_path: Path, audio) -> dict:
    """Load CrisperWhisper and transcribe one recording with it."""
    if settings.language == "auto-detect":
        raise ValueError("CrisperWhisper requires a language; select one instead of auto-detect.")
    model = load_model(model_path, settings.device, settings.compute_type, settings.cpu_threads)
    return transcribe_with_model(
        model,
        audio,
        language=settings.language,
        initial_prompt=settings.initial_prompt,
        temperature=settings.temperature,
        progress=settings.progress,
        log=partial(write_logfile, file_id=settings.file_id),
    )

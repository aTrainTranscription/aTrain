"""CrisperWhisper v2 adapter using its Transformers runtime."""

from __future__ import annotations

from functools import wraps
from pathlib import Path

from aTrain_core.backends.common import crisper_compute_type, words_to_segments
from aTrain_core.globals import SAMPLING_RATE
from aTrain_core.outputs import write_logfile
from aTrain_core.settings import Device, Settings


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


def _append_word_text(text: str, word: str) -> str:
    """Join Crisper words while keeping punctuation attached correctly."""
    if not text:
        return word
    if word.startswith((",", ".", "!", "?", ";", ":", "%", ")", "]", "}")):
        return text + word
    if text.endswith(("(", "[", "{")):
        return text + word
    return f"{text} {word}"


def group_word_segments(segments: list[dict]) -> list[dict]:
    """Merge Crisper's word segments into readable output cues."""
    grouped: list[dict] = []
    for segment in segments:
        if not grouped:
            grouped.append({**segment, "words": list(segment.get("words", []))})
            continue

        current = grouped[-1]
        gap = segment["start"] - current["end"]
        same_speaker = segment.get("speaker") == current.get("speaker")
        within_duration = segment["end"] - current["start"] <= 6.0
        if not same_speaker or gap >= 1.0 or not within_duration:
            grouped.append({**segment, "words": list(segment.get("words", []))})
            continue

        current["end"] = segment["end"]
        current["text"] = _append_word_text(current["text"], segment["text"])
        current["words"].extend(segment.get("words", []))
    return grouped


def transcribe(settings: Settings, model_path: Path, audio) -> dict:
    """Run CrisperWhisper in verbatim mode and normalize its word timestamps."""
    if settings.language == "auto-detect":
        raise ValueError("CrisperWhisper requires a language; select one instead of auto-detect.")
    if settings.initial_prompt:
        write_logfile(
            "CrisperWhisper does not support initial prompts; ignoring the setting.",
            settings.file_id,
        )
    if settings.temperature is not None:
        write_logfile(
            "CrisperWhisper does not support temperature; ignoring the setting.", settings.file_id
        )

    # Import lazily so the normal faster-whisper path neither initializes nor
    # requires the Transformers backend at module import time.
    from crisperwhisper import CrisperWhisperModel

    device = "cuda" if settings.device == Device.GPU else "cpu"
    # Transformers inference on CPU does not support float16. Crisper's
    # Transformers path also does not expose faster-whisper's int8 setting.
    compute_type = crisper_compute_type(settings)
    model = CrisperWhisperModel(
        model_path.as_posix(),
        backend="transformers",
        device=device,
        compute_type=compute_type,
    )
    _suppress_encoder_attentions(model)
    if settings.device == Device.CPU and settings.cpu_threads:
        import torch

        torch.set_num_threads(settings.cpu_threads)
    settings.progress["task"] = "Transcribe"
    settings.progress["current"] = 0
    settings.progress["total"] = 1
    result = model.transcribe(
        audio,
        sr=SAMPLING_RATE,
        language=settings.language,
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
    settings.progress["current"] = 1
    return {"segments": words_to_segments(words)}

"""Native Transformers Qwen3 ASR with its separate word aligner."""

from __future__ import annotations

import gc
import unicodedata
from pathlib import Path

from aTrain_core.backends.common import words_to_segments
from aTrain_core.globals import SAMPLING_RATE
from aTrain_core.load_resources import load_model_config_file
from aTrain_core.settings import ComputeType, Device, Settings

# The ASR supports more languages, but aTrain requires word timestamps for
# output files and speaker assignment. Only these have a supported aligner.
ALIGNMENT_LANGUAGES = {
    "zh": "Chinese",
    "en": "English",
    "yue": "Cantonese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "es": "Spanish",
}


def aligned_words(
    text: str, items: list[dict], *, offset: float, duration: float, separator: str = " "
) -> list[dict]:
    """Attach timing to the original text, including punctuation and spacing.

    Qwen's aligner drops punctuation. Match its letter/number/apostrophe tokens
    back to the ASR text so neither subtitles nor the transcript lose it. If
    they cannot be matched, keep the timing and use the aligner's tokens,
    joined by separator.
    """
    texts = _original_texts(text, [item["text"] for item in items])
    if texts is None:
        texts = [separator * (i > 0) + item["text"] for i, item in enumerate(items)]
    words = []
    for word, item in zip(texts, items, strict=True):
        # Clip to the chunk; max() keeps the lower bound for NaN.
        start = min(duration, max(0.0, item["start_time"]))
        end = min(duration, max(start, item["end_time"]))
        words.append({"word": word, "start": offset + start, "end": offset + end})
    return words


def _original_texts(text: str, tokens: list[str]) -> list[str] | None:
    """Split text at the token boundaries, or return None if the tokens do not map onto it."""
    positions = [
        i for i, char in enumerate(text) if unicodedata.category(char)[0] in "LN" or char == "'"
    ]
    aligned_text = "".join(tokens)
    if aligned_text != "".join(text[i] for i in positions):
        # Japanese tokenization normalizes fullwidth letters/numbers. Retain
        # their original spelling while matching the normalized aligner text.
        # Per character, so compositions across characters (ｶﾞ → ガ) do not match.
        normalized = []
        positions = []
        for i, char in enumerate(text):
            for normalized_char in unicodedata.normalize("NFKC", char):
                if unicodedata.category(normalized_char)[0] in "LN" or normalized_char == "'":
                    normalized.append(normalized_char)
                    positions.append(i)
        if aligned_text != "".join(normalized):
            return None
    if not all(tokens):
        return None

    texts = []
    cursor = boundary = 0
    for i, token in enumerate(tokens):
        cursor += len(token)
        end_boundary = len(text)
        if i < len(tokens) - 1:
            if positions[cursor - 1] == positions[cursor]:
                # One character expands into several tokens (㍿ → 株式, 会社).
                return None
            end_boundary = positions[cursor - 1] + 1
            while end_boundary < positions[cursor] and not text[end_boundary].isspace():
                end_boundary += 1
        texts.append(text[boundary:end_boundary])
        boundary = end_boundary
    return texts


def alignment_language(language: str | None) -> str:
    """Reject detected languages without timestamp support explicitly."""
    for code, name in ALIGNMENT_LANGUAGES.items():
        if language and language.lower() in (code, name.lower()):
            return code
    raise ValueError(
        f"Qwen3 word timestamps do not support language {language!r}. "
        f"Select one of: {', '.join(ALIGNMENT_LANGUAGES.values())}."
    )


def transcribe(settings: Settings, model_path: Path, audio) -> dict:
    """Transcribe bounded speech chunks, then align them on the original timeline."""
    # Keep Transformers, torch and audio inference out of GUI startup imports.
    import torch
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from transformers import (
        AutoProcessor,
        Qwen3ASRForConditionalGeneration,
        Qwen3ASRForTokenClassification,
    )

    language = None if settings.language == "auto-detect" else alignment_language(settings.language)
    device = "cuda" if settings.device == Device.GPU else "cpu"
    dtype = (
        torch.float32
        if settings.device == Device.CPU or settings.compute_type == ComputeType.FLOAT32
        else torch.float16
    )
    if settings.device == Device.CPU and settings.cpu_threads:
        torch.set_num_threads(settings.cpu_threads)
    duration = len(audio) / SAMPLING_RATE
    settings.progress.update({"task": "Transcribe", "current": 0, "total": duration * 2})
    chunks = get_speech_timestamps(
        audio,
        VadOptions(max_speech_duration_s=30, min_silence_duration_ms=500),
        sampling_rate=SAMPLING_RATE,
    )
    if not chunks:
        settings.progress["current"] = duration * 2
        return {"segments": []}

    # These paths come from get_model's pinned, checksum-verified download.
    processor = AutoProcessor.from_pretrained(  # nosec B615 — verified local checkpoint, no Hub lookup
        model_path, local_files_only=True, trust_remote_code=False
    )
    model = (
        Qwen3ASRForConditionalGeneration.from_pretrained(  # nosec B615 — verified local checkpoint
            model_path, dtype=dtype, local_files_only=True
        )
        .to(device)
        .eval()
    )
    generation = {"max_new_tokens": 1024, "do_sample": False}
    if settings.temperature is not None and settings.temperature > 0:
        generation.update({"do_sample": True, "temperature": settings.temperature})

    transcripts = []
    with torch.inference_mode():
        for chunk in chunks:
            inputs = processor.apply_transcription_request(
                audio=audio[chunk["start"] : chunk["end"]],
                language=language,
                prompt=settings.initial_prompt,
            ).to(device, dtype)
            output = model.generate(**inputs, **generation)
            tokens = output[0, inputs["input_ids"].shape[1] :]
            result = processor.decode(tokens, return_format="parsed")
            text = result["transcription"]
            if text.strip():
                detected_language = alignment_language(language or result["language"])
                transcripts.append((chunk, text, detected_language))
            settings.progress["current"] = chunk["end"] / SAMPLING_RATE

    # The 1.7B ASR and aligner need considerably less memory when loaded in
    # sequence. Drop generation tensors too: they may retain the final chunk.
    del model, processor, inputs, output, tokens
    gc.collect()
    if settings.device == Device.GPU:
        torch.cuda.empty_cache()
    if not transcripts:
        settings.progress["current"] = duration * 2
        return {"segments": []}

    settings.progress.update({"task": "Align words", "current": duration})
    # get_model has already verified the aligner next to the ASR model.
    aligner_path = model_path.parent / load_model_config_file()[settings.model]["dependencies"][0]
    processor = AutoProcessor.from_pretrained(  # nosec B615 — verified local checkpoint, no Hub lookup
        aligner_path, local_files_only=True, trust_remote_code=False
    )
    model = (
        Qwen3ASRForTokenClassification.from_pretrained(  # nosec B615 — verified local checkpoint
            aligner_path, dtype=dtype, local_files_only=True
        )
        .to(device)
        .eval()
    )
    words = []
    with torch.inference_mode():
        for chunk, text, detected_language in transcripts:
            inputs, word_lists = processor.prepare_forced_aligner_inputs(
                audio=audio[chunk["start"] : chunk["end"]],
                transcript=text,
                language=detected_language,
            )
            inputs = inputs.to(device, dtype)
            result = model(**inputs)
            items = processor.decode_forced_alignment(
                logits=result.logits,
                input_ids=inputs["input_ids"],
                word_lists=word_lists,
                timestamp_token_id=model.config.timestamp_token_id,
            )[0]
            separator = "" if detected_language in ("zh", "yue", "ja") else " "
            chunk_words = aligned_words(
                text,
                items,
                offset=chunk["start"] / SAMPLING_RATE,
                duration=(chunk["end"] - chunk["start"]) / SAMPLING_RATE,
                separator=separator,
            )
            if words and chunk_words:
                chunk_words[0]["word"] = separator + chunk_words[0]["word"]
            words.extend(chunk_words)
            settings.progress["current"] = duration + chunk["end"] / SAMPLING_RATE
    settings.progress["current"] = duration * 2
    return {"segments": words_to_segments(words)}

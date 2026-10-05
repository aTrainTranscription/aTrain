"""Convert backend-specific word timestamps to aTrain transcript segments."""

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass

from aTrain_core.settings import ComputeType, Device, Settings


def crisper_compute_type(settings: Settings) -> str:
    """Return the precision supported by CrisperWhisper's Transformers path."""
    if settings.device == Device.CPU or settings.compute_type == ComputeType.FLOAT32:
        return "float32"
    return "float16"


def _to_dict(value: object):
    """Convert the small record objects emitted by supported ASR backends."""
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    if is_dataclass(value):
        return {key: _to_dict(item) for key, item in asdict(value).items()}
    if hasattr(value, "_asdict") and callable(value._asdict):
        return {key: _to_dict(item) for key, item in value._asdict().items()}
    if hasattr(value, "__dict__"):
        return {key: _to_dict(item) for key, item in vars(value).items()}
    return value


def words_to_segments(words: Iterable[object]) -> list[dict]:
    """Return one aTrain segment for each timestamped word."""
    segments = []
    for word in words:
        word_dict = _to_dict(word)
        if word_dict.get("start") is None or word_dict.get("end") is None:
            continue
        segments.append(
            {
                "start": word_dict["start"],
                "end": word_dict["end"],
                "text": word_dict["word"].strip(),
                "words": [word_dict],
            }
        )
    return segments


def _append_word_text(text: str, word: str) -> str:
    """Join Crisper words while keeping punctuation attached correctly."""
    if not text:
        return word
    if word.startswith((",", ".", "!", "?", ";", ":", "%", ")", "]", "}")):
        return text + word
    if text.endswith(("(", "[", "{")):
        return text + word
    return f"{text} {word}"


SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")  # noqa: RUF001
SRT_MAX_DURATION = 7.0
_CLOSERS = "\"'”’»)]」』"  # noqa: RUF001


def ends_sentence(text: str) -> bool:
    """Return True when text ends a sentence, ignoring closing quotes and brackets."""
    return text.rstrip(_CLOSERS).endswith(SENTENCE_END)


def group_word_segments(
    segments: list[dict], join_raw: bool = False, max_duration: float = 20.0
) -> list[dict]:
    """Merge word segments into sentence-aware output cues.

    With join_raw, words are concatenated as emitted (faster-whisper words carry their own
    leading space, and none for languages written without spaces).
    """
    grouped: list[dict] = []
    for segment in segments:
        if not grouped:
            grouped.append({**segment, "words": list(segment.get("words", []))})
            continue

        current = grouped[-1]
        gap = segment["start"] - current["end"]
        same_speaker = segment.get("speaker") == current.get("speaker")
        within_duration = segment["end"] - current["start"] <= max_duration
        sentence_done = ends_sentence(current["text"])
        long_enough = current["end"] - current["start"] >= 3.0
        if not same_speaker or gap >= 2.0 or not within_duration or (sentence_done and long_enough):
            grouped.append({**segment, "words": list(segment.get("words", []))})
            continue

        current["end"] = segment["end"]
        if join_raw:
            current["text"] += "".join(w["word"] for w in segment.get("words", []))
        else:
            current["text"] = _append_word_text(current["text"], segment["text"])
        current["words"].extend(segment.get("words", []))
    return grouped

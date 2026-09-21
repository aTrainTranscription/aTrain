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
                "text": word_dict["word"],
                "words": [word_dict],
            }
        )
    return segments

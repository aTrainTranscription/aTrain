"""Preserve ASR text while attaching the forced aligner's word boundaries."""

import pytest
from aTrain_core.backends.qwen3_transformers import aligned_words, alignment_language


def timing(text, start=0.0, end=0.4):
    return {"text": text, "start_time": start, "end_time": end}


@pytest.mark.parametrize(
    "text,tokens,rendered",
    [
        ("Hello, world!", ["Hello", "world"], ["Hello,", " world!"]),
        (
            "It's well-known: 3.14%.",
            ["It's", "wellknown", "314"],
            ["It's", " well-known:", " 3.14%."],
        ),
        ("“Hello.” Yes?", ["Hello", "Yes"], ["“Hello.”", " Yes?"]),
        ("你好，世界！", ["你", "好", "世", "界"], ["你", "好，", "世", "界！"]),  # noqa: RUF001
        ("ありがとう。", ["ありがとう"], ["ありがとう。"]),
        (
            "２０２６年、ＡＩです。",
            ["2026", "年", "AI", "です"],
            ["２０２６", "年、", "ＡＩ", "です。"],  # noqa: RUF001
        ),
        ("안녕하세요 세계!", ["안녕하세요", "세계"], ["안녕하세요", " 세계!"]),
    ],
)
def test_punctuation_and_spacing_are_preserved(text, tokens, rendered):
    words = aligned_words(text, [timing(token) for token in tokens], offset=0, duration=2)
    assert [word["word"] for word in words] == rendered
    assert "".join(word["word"] for word in words) == text


def test_times_are_offset_and_clipped_to_the_audio_chunk():
    words = aligned_words("Hello.", [timing("Hello", 0.8, 1.04)], offset=30.0, duration=1.0)
    assert words == [{"word": "Hello.", "start": 30.8, "end": 31.0}]


@pytest.mark.parametrize(
    "text,tokens,separator,rendered",
    [
        # The aligner covers less text than the transcript.
        ("Hello world.", ["Hello"], " ", ["Hello"]),
        ("Hello world.", ["Hello", "word"], " ", ["Hello", " word"]),
        # NFKC composes half-width kana across characters (ｶ + ﾞ → ガ).
        ("ｶﾞｷﾞｸﾞｹﾞｺﾞです。", ["ガギグゲゴ", "です"], "", ["ガギグゲゴ", "です"]),
        # One character expands into several tokens (㍿ → 株式, 会社).
        ("㍿です。", ["株式", "会社", "です"], "", ["株式", "会社", "です"]),
    ],
)
def test_unmatched_tokens_fall_back_to_the_aligner_text(text, tokens, separator, rendered):
    items = [timing(token, i * 0.5, i * 0.5 + 0.4) for i, token in enumerate(tokens)]
    words = aligned_words(text, items, offset=10, duration=2, separator=separator)
    assert [word["word"] for word in words] == rendered
    assert [word["start"] for word in words] == [10 + i * 0.5 for i in range(len(tokens))]


@pytest.mark.parametrize(
    "start,end,clipped",
    [
        (float("nan"), 1, (0, 1)),
        (1, float("inf"), (1, 2)),
        (1, 0, (1, 1)),
        (1, float("nan"), (1, 1)),
    ],
)
def test_invalid_timestamps_are_clipped_to_the_chunk(start, end, clipped):
    (word,) = aligned_words("Hello", [timing("Hello", start, end)], offset=0, duration=2)
    assert (word["start"], word["end"]) == clipped


@pytest.mark.parametrize("language", ["en", "English", "ENGLISH"])
def test_detected_languages_use_alignment_codes(language):
    assert alignment_language(language) == "en"


@pytest.mark.parametrize("language", [None, "Arabic", "ar"])
def test_unsupported_detected_language_fails_explicitly(language):
    with pytest.raises(ValueError, match="word timestamps"):
        alignment_language(language)

"""Unit tests for aTrain_core.output_formats.netflix_subtitles, the Netflix-style SRT output.

`netflix_issues` ports the checks of Subtitle Edit's Netflix quality check
(https://github.com/SubtitleEdit/subtitleedit, MIT License, Copyright (c)
Nikolaj Olsson) that apply to audio-only output.
Shot changes need the video, and italics or number spelling would change the
transcript, so those are left out. The movie fixtures are Whisper output for
3-minute clips of public domain films; see the "source" key of each file.
"""

import json
from pathlib import Path

import pytest
from aTrain_core.output_formats.netflix_subtitles import (
    SRT_MAX_DURATION,
    srt_cues,
    srt_document,
    srt_length,
    srt_profile,
    srt_wrap,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "srt"
MOVIES = sorted(path.stem for path in FIXTURES.glob("*.json"))


def _seconds(timestamp):
    hours, minutes, rest = timestamp.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def parse_srt(text):
    cues = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        start, end = lines[1].split(" --> ")
        cues.append((_seconds(start), _seconds(end), lines[2:]))
    return cues


def netflix_issues(cues, language):
    """Returns (rule, cue number) for every Netflix rule a parsed SRT breaks."""
    profile = srt_profile(language)
    issues = []
    for index, (start, end, lines) in enumerate(cues):
        number, duration, text = index + 1, end - start, " ".join(lines)
        if any(srt_length(line, profile) > profile.line_length for line in lines):
            issues.append(("max line length", number))
        if len(lines) > 2:
            issues.append(("two lines maximum", number))
        if len(lines) == 2 and srt_length(text, profile) <= profile.line_length:
            issues.append(("text can fit on one line", number))
        if duration < profile.min_duration - 0.001:
            issues.append(("minimum duration", number))
        if duration > SRT_MAX_DURATION + 0.001:
            issues.append(("maximum duration", number))
        if duration > 0 and srt_length(text, profile) / duration > profile.chars_per_second + 0.01:
            issues.append(("maximum characters per second", number))
        if any(line != line.strip() or "  " in line for line in lines):
            issues.append(("white space", number))
        if "..." in text:
            issues.append(("ellipses not three dots", number))
        if index + 1 < len(cues):
            gap = cues[index + 1][0] - end
            if gap < profile.min_gap - 0.001:
                issues.append(("two frames gap", number))
            elif profile.min_gap + 0.001 < gap < profile.bridge_gap - 0.001:
                issues.append(("bridge gaps", number))
    return issues


def _render(segments, language):
    return parse_srt(srt_document(segments, language))


def _words(*timed_words):
    """Builds Whisper-style word dicts from (start, end, token) tuples."""
    return [{"start": start, "end": end, "word": word} for start, end, word in timed_words]


def _segment(words, **extra):
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": "".join(w["word"] for w in words),
        "words": words,
        **extra,
    }


@pytest.mark.parametrize("movie", MOVIES)
def test_movie_clips_follow_netflix_rules(movie):
    fixture = json.loads((FIXTURES / f"{movie}.json").read_text(encoding="utf-8"))
    cues = _render(fixture["segments"], fixture["language"])
    # Fast speech cannot always meet the reading speed without rewording the transcript.
    issues = [
        i
        for i in netflix_issues(cues, fixture["language"])
        if i[0] != "maximum characters per second"
    ]
    assert issues == []


def test_movie_clips_keep_every_word():
    for movie in MOVIES:
        fixture = json.loads((FIXTURES / f"{movie}.json").read_text(encoding="utf-8"))
        expected = " ".join(s["text"] for s in fixture["segments"]).split()
        actual = " ".join(cue[2] for cue in srt_cues(fixture["segments"], "en")).split()
        assert actual == expected, movie


def test_long_sentence_is_wrapped_after_punctuation():
    text = "We ought to make the day the time changes, the first day of summer."
    assert srt_wrap(text, srt_profile("en")) == [
        "We ought to make the day the time changes,",
        "the first day of summer.",
    ]


def test_wrap_does_not_break_after_an_article():
    lines = srt_wrap(
        "I was walking down to the old harbour with a friend of mine", srt_profile("en")
    )
    assert not lines[0].lower().endswith((" the", " a"))


def test_short_text_stays_on_one_line():
    assert srt_wrap("Look at this thing.", srt_profile("en")) == ["Look at this thing."]


def test_word_pieces_are_joined_without_spaces():
    words = _words((0.0, 0.3, " Well,"), (0.3, 0.5, " it's"), (0.5, 0.7, " 8"), (0.7, 0.8, " o"),
                   (0.8, 1.0, "'clock."))  # fmt: skip
    assert srt_cues([_segment(words)], "en")[0][2] == "Well, it's 8 o'clock."


def test_unpunctuated_text_is_split_at_pauses():
    first = [
        (i * 0.3, i * 0.3 + 0.25, f" {w}")
        for i, w in enumerate(["it", "wasn't", "much", "of", "a", "club", "really"])
    ]
    second = [
        (3.0 + i * 0.3, 3.25 + i * 0.3, f" {w}")
        for i, w in enumerate(["you", "know", "the", "kind", "of", "joint"])
    ]
    words = _words(*first, *second)
    cues = srt_cues([_segment(words)], "en")
    assert [cue[2] for cue in cues] == [
        "it wasn't much of a club really",
        "you know the kind of joint",
    ]


def test_overlong_segment_is_split_into_cues_within_limits():
    text = "and then we went to the market and bought some apples and pears for the long trip home"
    words = _words(*[(i * 0.25, i * 0.25 + 0.2, f" {w}") for i, w in enumerate(text.split())])
    cues = srt_cues([_segment(words)], "en")
    assert len(cues) == 2
    assert all(len(line) <= 42 for cue in cues for line in srt_wrap(cue[2], srt_profile("en")))


def test_speaker_change_starts_a_new_cue():
    first = _segment(_words((0.0, 0.4, " Where"), (0.4, 0.8, " to")), speaker="SPEAKER_00")
    second = _segment(_words((0.8, 1.2, " Home"), (1.2, 2.0, " now")), speaker="SPEAKER_01")
    cues = srt_cues([first, second], "en")
    assert [(cue[2], cue[3]) for cue in cues] == [
        ("Where to", "SPEAKER_00"),
        ("Home now", "SPEAKER_01"),
    ]


def test_too_short_cue_is_merged_into_the_next():
    look = _segment(_words((20.16, 20.44, " Look.")))
    there = _segment(_words((20.50, 20.70, " There"), (20.70, 20.85, " it"), (20.85, 21.0, " is.")))
    assert [cue[2] for cue in srt_cues([look, there], "en")] == ["Look. There it is."]


def test_cue_is_held_for_reading_time_and_gaps_are_bridged():
    first = _segment(_words((0.0, 0.3, " No.")))
    second = _segment(_words((1.2, 1.6, " Yes.")))
    third = _segment(_words((5.0, 5.4, " Maybe.")))
    cues = srt_cues([first, second, third], "en")
    assert cues[0][1] == pytest.approx(1.2 - 2 / 24)  # gap under 0.5 s bridged to two frames
    assert cues[1][1] == pytest.approx(1.2 + 5 / 6)  # held for the minimum duration


def test_segment_without_words_is_kept():
    cues = srt_cues([{"start": 1.0, "end": 2.5, "text": " Hello there.", "words": []}], "en")
    assert cues[0][:3] == [1.0, 2.5, "Hello there."]


def test_language_profiles():
    english, german, japanese, korean = (srt_profile(code) for code in ("en", "de", "ja", "ko"))
    assert (english.line_length, english.chars_per_second) == (42, 20)
    assert (german.line_length, german.chars_per_second) == (42, 17)
    assert (japanese.line_length, japanese.min_duration, japanese.min_gap) == (13, 0.5, 0.0)
    assert srt_profile("auto-detect").line_length == 42
    assert srt_length("안녕 OK", korean) == 2 + 0.5 * 3


def test_chinese_is_joined_without_spaces_and_wrapped_by_characters():
    text = "我们今天去市场买了很多苹果和梨，准备明天带回家给大家吃"  # noqa: RUF001
    words = _words(*[(i * 0.2, i * 0.2 + 0.2, char) for i, char in enumerate(text)])
    cues = srt_cues([_segment(words)], "zh")
    profile = srt_profile("zh")
    assert "".join(cue[2] for cue in cues) == text
    assert all(len(line) <= 16 for cue in cues for line in srt_wrap(cue[2], profile))
    assert " " not in "".join(cue[2] for cue in cues)


def test_srt_document_writes_netflix_cues():
    words = _words((0.0, 0.3, " Wait..."), (0.35, 0.6, " what?"))
    cues = _render([_segment(words)], "en")
    assert cues == [(0.0, pytest.approx(5 / 6, abs=0.001), ["Wait… what?"])]


def test_word_pieces_spanning_long_silence_do_not_break_splitting():
    words = _words((0.0, 0.5, " in"), (0.5, 1.0, " those"), (1.0, 5.0, " da"), (5.0, 9.0, "ys"))
    cues = srt_cues([_segment(words)], "en")
    assert " ".join(cue[2] for cue in cues) == "in those days"

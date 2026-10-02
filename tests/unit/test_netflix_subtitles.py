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
    netflix_issues,
    parse_srt,
    srt_cues,
    srt_document,
    srt_length,
    srt_profile,
    srt_wrap,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "srt"
MOVIES = sorted(path.stem for path in FIXTURES.glob("*.json"))
# Cues per movie clip that stay faster than the reading speed: the speech itself is faster,
# and meeting the limit would mean rewording the transcript. Lower these when it improves.
TOO_FAST = {"detour": 6, "his_girl_friday": 21}


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
    issues = netflix_issues(srt_document(fixture["segments"], "en"), "en")
    too_fast = [i for i in issues if i[0] == "maximum characters per second"]
    assert [i for i in issues if i not in too_fast] == []
    assert len(too_fast) <= TOO_FAST[movie]


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
    second = _segment(_words((1.5, 1.9, " Home"), (1.9, 2.7, " now")), speaker="SPEAKER_01")
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
    third = _segment(_words((5.0, 5.1, " Maybe.")))
    cues = srt_cues([first, second, third], "en")
    assert cues[0][1] == pytest.approx(1.2 - 2 / 24)  # gap under 0.5 s bridged to two frames
    assert cues[1][1] == pytest.approx(1.6 + 0.5)  # held half a second past the speech
    assert cues[2][1] == pytest.approx(5.0 + 5 / 6)  # held for the minimum duration


def test_segment_without_words_is_kept():
    cues = srt_cues([{"start": 1.0, "end": 2.5, "text": " Hello there.", "words": []}], "en")
    assert [cue[2] for cue in cues] == ["Hello there."]
    assert cues[0][0] == 1.0


def test_long_segment_without_words_is_resegmented():
    text = (
        "This is a long fallback segment with enough words to wrap into several "
        "different subtitle lines and it goes on for ten whole seconds."
    )
    document = srt_document([{"start": 0.0, "end": 10.0, "text": text}], "en")
    assert netflix_issues(document, "en") == []
    assert " ".join(" ".join(cue[2]) for cue in parse_srt(document)) == text


def test_language_profiles():
    english, german, japanese, korean = (srt_profile(code) for code in ("en", "de", "ja", "ko"))
    assert (english.line_length, english.chars_per_second) == (42, 20)
    assert (german.line_length, german.chars_per_second) == (42, 17)
    assert (japanese.line_length, japanese.min_duration, japanese.min_gap) == (13, 0.5, 2 / 24)
    assert srt_profile("auto-detect").line_length == 42
    assert srt_length("안녕 OK", korean) == 2 + 0.5 * 3


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("ja", "HelloNetflixWorld", 8.5),
        ("ja", "はい。", 3),
        ("ko", "안녕…", 2.5),
        ("th", "ที่" * 13, 13),
    ],
)
def test_characters_are_counted_per_language(language, text, expected):
    assert srt_length(text, srt_profile(language)) == expected


def test_thai_lines_keep_marks_with_their_letters():
    lines = srt_wrap("ที่" * 40, srt_profile("th"))
    assert len(lines) == 2
    assert not any(line[0] in "\u0e35\u0e48" for line in lines)


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [("zh", "今天下雨，明天晴天。", "今天下雨 明天晴天"), ("ja", "はい、そうです。", "はい そうです"),  # noqa: RUF001
     ("th", "ไปไหน? ไปบ้าน.", "ไปไหน ไปบ้าน")],
)  # fmt: skip
def test_punctuation_rules_per_language(language, text, expected):
    words = _words((0.0, 3.0, text))
    assert parse_srt(srt_document([_segment(words)], language))[0][2] == [expected]


def test_names_are_not_split_across_lines():
    lines = srt_wrap("Yesterday I met Alexander Hamilton near the station.", srt_profile("en"))
    assert "Alexander\nHamilton" not in "\n".join(lines)


def test_quick_speaker_turns_share_a_dual_speaker_cue():
    yes = _segment(_words((0.0, 0.4, " Yes.")), speaker="A")
    okay = _segment(_words((0.5, 1.2, " Okay.")), speaker="B")
    document = srt_document([yes, okay], "en")
    assert parse_srt(document)[0][2] == ["-Yes.", "-Okay."]
    assert netflix_issues(document, "en") == []
    assert parse_srt(srt_document([yes, okay], "fr"))[0][2] == ["- Yes.", "- Okay."]


def test_speakers_within_a_segment_are_kept_apart():
    words = _words((0.0, 0.35, " Yes."), (0.35, 0.7, " No."))
    words[0]["speaker"], words[1]["speaker"] = "A", "B"
    assert parse_srt(srt_document([_segment(words, speaker="A")], "en"))[0][2] == ["-Yes.", "-No."]


def test_unresolvable_short_cue_is_reported():
    first = _segment(_words((0.0, 0.4, " " + "word " * 9 + "end.")), speaker="A")
    second = _segment(_words((0.5, 1.5, " " + "other " * 6 + "end.")), speaker="B")
    issues = netflix_issues(srt_document([first, second], "en"), "en")
    assert ("minimum duration", 1) in issues


def test_too_fast_neighbours_are_merged_when_that_reads_slower():
    first = _segment(_words((0.0, 0.7, " Please bring the paperwork tomorrow.")))
    second = _segment(_words((1.2, 2.5, " I'll be there.")))
    cues = srt_cues([first, second], "en")
    assert [cue[2] for cue in cues] == ["Please bring the paperwork tomorrow. I'll be there."]
    assert len(cues[0][2]) / (cues[0][1] - cues[0][0]) <= 20


def test_cues_are_not_merged_across_a_long_silence():
    first = _segment(_words((0.0, 0.7, " Please bring the paperwork tomorrow.")))
    second = _segment(_words((3.0, 3.5, " I'll be there.")))
    assert len(srt_cues([first, second], "en")) == 2


def test_japanese_cues_keep_the_two_frame_gap():
    cues = srt_cues(
        [_segment(_words((0.0, 1.0, "はい。"))), _segment(_words((1.0, 2.0, "いいえ。")))], "ja"
    )
    assert len(cues) == 1 or cues[1][0] - cues[0][1] >= 2 / 24 - 1e-9


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
    assert cues == [(0.0, pytest.approx(1.1, abs=0.001), ["Wait… what?"])]


def test_word_pieces_spanning_long_silence_do_not_break_splitting():
    words = _words((0.0, 0.5, " in"), (0.5, 1.0, " those"), (1.0, 5.0, " da"), (5.0, 9.0, "ys"))
    cues = srt_cues([_segment(words)], "en")
    assert " ".join(cue[2] for cue in cues) == "in those days"


def test_punctuation_only_cue_is_left_out():
    segments = [_segment(_words((0.0, 0.5, "。"))), _segment(_words((3.0, 4.0, "你好。")))]
    document = srt_document(segments, "zh")
    assert [cue[2] for cue in parse_srt(document)] == [["你好"]]
    assert document.startswith("1\n")
    assert netflix_issues(document, "zh") == []


@pytest.mark.parametrize(
    ("pieces", "expected"), [(("O", "'Reilly."), "O'Reilly."), (("X", "-ray."), "X-ray.")]
)
def test_word_pieces_without_a_leading_space_stay_joined(pieces, expected):
    other = _segment(_words((0.0, 0.5, " Hello.")))
    word = _segment(_words((3.0, 3.3, pieces[0]), (3.3, 3.8, pieces[1])))
    assert srt_cues([other, word], "en")[1][2] == expected


def test_long_pause_after_a_comma_starts_a_new_cue():
    wait = _segment(_words((0.0, 0.5, " Wait,")))
    okay = _segment(_words((6.0, 6.5, " okay.")))
    cues = srt_cues([wait, okay], "en")
    assert [cue[2] for cue in cues] == ["Wait,", "okay."]
    assert cues[0][1] < 6.0

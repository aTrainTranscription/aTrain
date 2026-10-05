import pandas as pd
from aTrain_core.backends.common import (
    SRT_MAX_DURATION,
    group_word_segments,
    words_to_segments,
)
from aTrain_core.outputs import assign_word_speakers, smooth_speaker_flips


def diarization(*rows):
    return pd.DataFrame(rows, columns=["start", "end", "speaker"])


def test_word_crossing_boundary_uses_speaker_at_word_start():
    result = {"segments": [{"start": 0.0, "end": 1.2, "words": [{"start": 0.9, "end": 1.2}]}]}

    assign_word_speakers(diarization((0.0, 1.0, "A"), (0.95, 2.0, "B")), result)

    assert result["segments"][0]["words"][0]["speaker"] == "A"
    assert result["segments"][0]["speaker"] == "A"


def test_word_starting_after_boundary_uses_new_speaker():
    result = {"segments": [{"start": 0.0, "end": 1.2, "words": [{"start": 1.01, "end": 1.2}]}]}

    assign_word_speakers(diarization((0.0, 1.0, "A"), (0.95, 2.0, "B")), result)

    assert result["segments"][0]["words"][0]["speaker"] == "B"


def test_overlapping_tracks_have_stable_tie_breaking():
    result = {"segments": [{"start": 0.0, "end": 1.0, "words": [{"start": 0.5, "end": 0.6}]}]}

    assign_word_speakers(diarization((0.0, 1.0, "A"), (0.0, 1.0, "B")), result)

    assert result["segments"][0]["words"][0]["speaker"] == "A"


def test_segment_speaker_comes_from_word_labels():
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "words": [{"start": 0.0, "end": 0.4}, {"start": 0.5, "end": 1.9}],
            }
        ]
    }

    assign_word_speakers(diarization((0.0, 0.4, "A"), (0.4, 2.0, "B")), result)

    assert result["segments"][0]["speaker"] == "B"


def test_segment_without_labeled_words_uses_overlap_majority():
    result = {"segments": [{"start": 0.0, "end": 2.0, "words": [{"text": "un-timestamped"}]}]}

    assign_word_speakers(diarization((0.0, 0.1, "A"), (0.1, 2.0, "B")), result)

    assert result["segments"][0]["speaker"] == "B"


def test_empty_diarization_leaves_segment_and_word_unlabeled():
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "words": [{"start": 0.1, "end": 0.2}],
            }
        ]
    }

    assign_word_speakers(diarization(), result, fill_nearest=True)

    assert "speaker" not in result["segments"][0]
    assert "speaker" not in result["segments"][0]["words"][0]


def test_one_word_segment_speaker_follows_word_onset():
    result = {"segments": [{"start": 0.9, "end": 1.2, "words": [{"start": 0.9, "end": 1.2}]}]}

    assign_word_speakers(diarization((0.0, 1.0, "A"), (0.95, 2.0, "B")), result)

    assert result["segments"][0]["speaker"] == "A"


def gap_result(*words):
    return {"segments": words_to_segments({"word": w, "start": s, "end": e} for w, s, e in words)}


def test_gap_word_takes_nearest_turn():
    result = gap_result((" So", 2.6, 2.9))

    assign_word_speakers(diarization((0.0, 1.0, "A"), (3.0, 5.0, "B")), result)

    assert result["segments"][0]["speaker"] == "B"


def test_gap_word_closer_to_previous_turn():
    result = gap_result((" So", 1.1, 1.3))

    assign_word_speakers(diarization((0.0, 1.0, "A"), (3.0, 5.0, "B")), result)

    assert result["segments"][0]["speaker"] == "A"


def test_words_before_first_turn_take_first_speaker():
    result = gap_result((" Well", 0.0, 0.3), (" yes", 0.4, 0.6))

    assign_word_speakers(diarization((1.0, 2.0, "A"), (3.0, 5.0, "B")), result)

    assert [s["speaker"] for s in result["segments"]] == ["A", "A"]


def test_gap_fill_labels_words():
    result = gap_result((" So", 2.6, 2.9))

    assign_word_speakers(diarization((0.0, 1.0, "A"), (3.0, 5.0, "B")), result)

    assert result["segments"][0]["words"][0]["speaker"] == "B"


def cues(*words, join_raw=False, max_duration=20.0):
    """Group (text, start, end[, speaker]) tuples like the transcription pipeline."""
    segments = words_to_segments({"word": w[0], "start": w[1], "end": w[2]} for w in words)
    for segment, w in zip(segments, words, strict=True):
        if len(w) == 4:
            segment["speaker"] = w[3]
    return [
        (c["text"], c["start"], c["end"])
        for c in group_word_segments(segments, join_raw, max_duration)
    ]


def test_cue_ends_at_sentence_boundary():
    result = cues((" This", 0.0, 1.0), (" is", 1.0, 2.0), (" long.", 2.0, 3.5), (" Next", 3.6, 4.0))

    assert result == [("This is long.", 0.0, 3.5), ("Next", 3.6, 4.0)]


def test_short_sentences_share_a_cue():
    result = cues((" Yes.", 0.0, 0.5), (" Okay.", 0.6, 1.0), (" Go", 1.1, 1.5))

    assert result == [("Yes. Okay. Go", 0.0, 1.5)]


def test_long_pause_starts_new_cue():
    result = cues((" wait", 0.0, 0.5), (" here", 2.5, 3.0))

    assert result == [("wait", 0.0, 0.5), ("here", 2.5, 3.0)]


def test_short_pause_inside_sentence_keeps_cue():
    result = cues((" wait", 0.0, 0.5), (" here", 1.5, 2.0))

    assert result == [("wait here", 0.0, 2.0)]


def test_unpunctuated_speech_is_capped():
    words = [(" w", float(i), float(i) + 0.9) for i in range(25)]

    result = cues(*words)

    assert [c[1] for c in result] == [0.0, 20.0]


def test_speaker_change_starts_new_cue():
    result = cues((" Right?", 0.0, 0.5, "A"), (" Yes", 0.6, 1.0, "B"))

    assert result == [("Right?", 0.0, 0.5), ("Yes", 0.6, 1.0)]


def test_cjk_sentence_end_splits_cue():
    result = cues(("你好。", 0.0, 3.5), ("我", 3.6, 4.0), join_raw=True)

    assert result == [("你好。", 0.0, 3.5), ("我", 3.6, 4.0)]


def test_sentence_end_inside_quotes():
    result = cues((" said", 0.0, 1.0), (' "done."', 1.0, 3.5), (" Next", 3.6, 4.0))

    assert result == [('said "done."', 0.0, 3.5), ("Next", 3.6, 4.0)]


def test_join_raw_keeps_emitted_spacing():
    result = cues((" Hello", 0.0, 0.5), (" world.", 0.6, 1.0), join_raw=True)

    assert result == [("Hello world.", 0.0, 1.0)]


def speakers(*words):
    """Smooth (text, start, end, speaker) segments and return their speakers."""
    segments = [{"text": w[0], "start": w[1], "end": w[2], "speaker": w[3]} for w in words]
    return [s["speaker"] for s in smooth_speaker_flips(segments)]


def test_single_word_flip_mid_sentence_is_absorbed():
    result = speakers(
        ("I", 0.0, 0.2, "A"),
        ("think", 0.3, 0.6, "A"),
        ("that", 0.7, 0.9, "B"),
        ("is", 1.0, 1.2, "A"),
    )

    assert result == ["A", "A", "A", "A"]


def test_flip_relabels_words():
    segments = [
        {"text": "I", "start": 0.0, "end": 0.2, "speaker": "A"},
        {"text": "so", "start": 0.3, "end": 0.5, "speaker": "B", "words": [{"speaker": "B"}]},
        {"text": "go", "start": 0.6, "end": 0.8, "speaker": "A"},
    ]

    smooth_speaker_flips(segments)

    assert segments[1]["words"][0]["speaker"] == "A"


def test_interjection_after_sentence_end_is_kept():
    result = speakers(("right?", 0.0, 0.4, "A"), ("Yeah.", 0.5, 0.8, "B"), ("So", 0.9, 1.1, "A"))

    assert result == ["A", "B", "A"]


def test_flip_with_pause_is_kept():
    result = speakers(("I", 0.0, 0.2, "A"), ("well", 1.2, 1.4, "B"), ("go", 2.4, 2.6, "A"))

    assert result == ["A", "B", "A"]


def test_three_word_run_is_kept():
    result = speakers(
        ("I", 0.0, 0.5, "A"),
        ("no", 0.6, 0.7, "B"),
        ("no", 0.8, 0.9, "B"),
        ("no", 1.0, 1.1, "B"),
        ("go", 1.2, 1.5, "A"),
    )

    assert result == ["A", "B", "B", "B", "A"]


def test_flip_at_sentence_edge_is_absorbed():
    assert speakers(("so", 0.0, 0.2, "B"), ("I", 0.3, 0.5, "A"), ("go.", 0.6, 0.8, "A")) == [
        "A",
        "A",
        "A",
    ]
    assert speakers(("I", 0.0, 0.2, "A"), ("go", 0.3, 0.5, "A"), ("so.", 0.6, 0.8, "B")) == [
        "A",
        "A",
        "A",
    ]


def test_last_word_of_sentence_stays_with_its_speaker():
    result = speakers(
        ("get", 0.0, 0.3, "A"),
        ("the", 0.3, 0.5, "A"),
        ("floor.", 0.5, 0.8, "B"),
        ("No,", 1.0, 1.3, "B"),
        ("I'm", 1.3, 1.5, "B"),
    )

    assert result == ["A", "A", "A", "B", "B"]


def test_flip_after_sentence_end_joins_next_sentence():
    result = speakers(
        ("Jonathan.", 0.0, 0.4, "A"),
        ("And", 0.6, 0.8, "B"),
        ("then", 0.8, 1.0, "B"),
        ("I", 1.0, 1.1, "A"),
        ("think", 1.1, 1.4, "A"),
        ("so.", 1.4, 1.7, "A"),
    )

    assert result == ["A", "A", "A", "A", "A", "A"]


def test_interruption_inside_sentence_is_kept():
    words = [(w, i * 0.3, i * 0.3 + 0.25, "A" if i < 3 else "B") for i, w in enumerate("abcdef")]

    assert speakers(*words) == ["A", "A", "A", "B", "B", "B"]


def test_tie_keeps_both_speakers():
    assert speakers(("well", 0.0, 0.2, "A"), ("go", 0.3, 0.5, "B")) == ["A", "B"]


def test_subtitle_cap():
    words = [(" w", float(i), float(i) + 0.9) for i in range(25)]

    result = cues(*words, max_duration=SRT_MAX_DURATION)

    assert [c[1] for c in result] == [0.0, 7.0, 14.0, 21.0]
    assert all(end - start <= SRT_MAX_DURATION for _, start, end in result)


def test_subtitle_cap_keeps_sentence_split():
    result = cues(
        (" This", 0.0, 1.0),
        (" is", 1.0, 2.0),
        (" long.", 2.0, 4.0),
        (" Next", 4.1, 5.0),
        max_duration=SRT_MAX_DURATION,
    )

    assert result == [("This is long.", 0.0, 4.0), ("Next", 4.1, 5.0)]

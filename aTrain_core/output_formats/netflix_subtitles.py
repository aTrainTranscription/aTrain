"""Netflix-style subtitle cues built from Whisper word timestamps."""

import time
from dataclasses import dataclass

# Subtitle rules from the Netflix Timed Text Style Guides. The per-language limits follow the
# Netflix quality check of Subtitle Edit (https://github.com/SubtitleEdit/subtitleedit,
# MIT License, Copyright (c) Nikolaj Olsson) and the Netflix language guides; languages
# without an entry use the defaults.
SRT_LINE_LENGTH = {"ja": 13, "ko": 16, "th": 35, "zh": 16}
SRT_CHARS_PER_SECOND = {"ar": 20, "en": 20, "hi": 22, "ja": 4, "ko": 12, "zh": 9}
SRT_DEFAULT_LINE_LENGTH = 42
SRT_DEFAULT_CHARS_PER_SECOND = 17
SRT_MAX_DURATION = 7.0
SRT_FRAME = 1 / 24
SRT_UNSPACED_LANGUAGES = {"ja", "zh", "th", "lo", "my", "km"}
SRT_PUNCTUATION = (".", ",", "?", "!", ";", ":", "…", "。", "，", "、", "？", "！", "；", "：")  # noqa: RUF001
SRT_SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")  # noqa: RUF001
# Pauses that end a sentence in unpunctuated text, as in Subtitle Edit's "add periods" step
SRT_PAUSE_SENTENCE = 0.6
SRT_PAUSE_ALWAYS = 1.25
SRT_EN_SKIP_LAST = {"with", "however", "a"}
SRT_EN_SKIP_FIRST = {"to", "and", "but", "with", "off", "have"}
# English line breaking: break before these words, never after those
SRT_EN_BREAK_BEFORE = {
    "and", "but", "or", "nor", "so", "yet", "because", "although", "if", "when", "while",
    "that", "which", "who", "where", "after", "before", "until", "than", "as",
    "to", "of", "in", "on", "at", "for", "with", "from", "into", "about", "by", "over",
}  # fmt: skip
SRT_EN_NO_BREAK_AFTER = {
    "a", "an", "the", "i", "you", "he", "she", "we", "they", "it", "my", "your", "his",
    "her", "our", "their", "this", "these", "those", "not", "don't", "can't", "won't",
    "i'm", "you're", "we're", "they're", "he's", "she's", "it's", "i'll", "you'll", "we'll",
    "mr", "mrs", "ms", "dr", "mr.", "mrs.", "ms.", "dr.",
}  # fmt: skip


@dataclass(frozen=True)
class SrtProfile:
    """Netflix subtitle limits for one language."""

    language: str
    line_length: int
    chars_per_second: int
    min_duration: float
    min_gap: float
    bridge_gap: float
    spaced: bool


def srt_profile(language):
    """Returns the Netflix subtitle limits for a Whisper language code."""
    language = str(language or "").split("-")[0].lower()
    language = "zh" if language == "yue" else language
    japanese = language == "ja"  # Japanese allows 0.5 s cues and has no gap rules
    return SrtProfile(
        language=language,
        line_length=SRT_LINE_LENGTH.get(language, SRT_DEFAULT_LINE_LENGTH),
        chars_per_second=SRT_CHARS_PER_SECOND.get(language, SRT_DEFAULT_CHARS_PER_SECOND),
        min_duration=0.5 if japanese else 5 / 6,
        min_gap=0.0 if japanese else 2 * SRT_FRAME,
        bridge_gap=0.0 if japanese else 0.5,
        spaced=language not in SRT_UNSPACED_LANGUAGES,
    )


def srt_length(text, profile):
    """Counts characters the Netflix way: in Korean, Latin letters, spaces and punctuation count half."""
    if profile.language == "ko":
        return sum(1 if ord(char) >= 0x1100 else 0.5 for char in text)
    return len(text)


def _srt_join(tokens, profile):
    """Joins word tokens into text."""
    tokens = [str(token) for token in tokens]
    if not profile.spaced or any(token.startswith(" ") for token in tokens):
        # Whisper marks word starts with a leading space; other tokens continue the word.
        return "".join(tokens).strip()
    text = ""
    for token in tokens:
        token = token.strip()
        if text and not token.startswith(SRT_PUNCTUATION):
            text += " "
        text += token
    return text


def srt_wrap(text, profile):
    """Splits text into at most two lines, preferring Netflix-style line breaks."""
    if srt_length(text, profile) <= profile.line_length:
        return [text]
    english = profile.language == "en"
    separator = " " if profile.spaced else ""
    units = text.split(" ") if profile.spaced else list(text)
    best, best_score = [text], None
    for i in range(1, len(units)):
        top, bottom = separator.join(units[:i]), separator.join(units[i:])
        top_length, bottom_length = srt_length(top, profile), srt_length(bottom, profile)
        score = abs(top_length - bottom_length)
        score += 100 * (max(top_length, bottom_length) > profile.line_length)
        score += 100 * units[i].startswith(SRT_PUNCTUATION)
        if units[i - 1].endswith(SRT_PUNCTUATION):
            score -= 30
        elif english and units[i].lower().strip("".join(SRT_PUNCTUATION)) in SRT_EN_BREAK_BEFORE:
            score -= 15
        if english and units[i - 1].lower() in SRT_EN_NO_BREAK_AFTER:
            score += 60
        elif english and units[i - 1].lower() in SRT_EN_BREAK_BEFORE:
            score += 15
        if profile.spaced and i <= 2:
            score += 20  # avoid a top line of just one or two words
        if top_length > bottom_length:
            score += 2  # prefer a bottom-heavy pyramid
        if best_score is None or score < best_score:
            best, best_score = [top, bottom], score
    return best


def _srt_fits(text, profile):
    return all(srt_length(line, profile) <= profile.line_length for line in srt_wrap(text, profile))


def _srt_sentence_end(previous, following, profile):
    """Whether a sentence ends between two words, by punctuation or by a long enough pause."""
    text = previous["word"].strip()
    if text.endswith(SRT_SENTENCE_END):
        return True
    if text.endswith(SRT_PUNCTUATION):
        return False
    pause = following["start"] - previous["end"]
    if pause > SRT_PAUSE_ALWAYS:
        return True
    if pause <= SRT_PAUSE_SENTENCE:
        return False
    return not (
        profile.language == "en"
        and (
            text.lower() in SRT_EN_SKIP_LAST
            or following["word"].strip().lower() in SRT_EN_SKIP_FIRST
        )
    )


def _srt_break(words, i, profile, spaced):
    """Scores how natural a cue break before words[i] is, or None inside a word."""
    if spaced and not words[i]["word"].startswith(" "):
        return None  # Whisper starts words with a space; other tokens continue a word
    previous, following = words[i - 1]["word"].strip().lower(), words[i]["word"].strip().lower()
    score = 30 * (previous.endswith(SRT_PUNCTUATION) and not previous.endswith(SRT_SENTENCE_END))
    score += 40 * min(words[i]["start"] - words[i - 1]["end"], 1.0)
    if profile.language == "en":
        score += 15 * (following in SRT_EN_BREAK_BEFORE) - 15 * (previous in SRT_EN_BREAK_BEFORE)
        score -= 60 * (previous in SRT_EN_NO_BREAK_AFTER)
    return score


def _srt_split(words, profile):
    """Splits one sentence into the fewest cues that fit, breaking at the most natural places."""
    spaced = profile.spaced and any(word["word"].startswith(" ") for word in words)
    breaks = [None] + [_srt_break(words, i, profile, spaced) for i in range(1, len(words))] + [0]
    best = [(0.0, 0)] + [None] * len(words)  # (cost, start of the last cue) per end index
    for end in range(1, len(words) + 1):
        if breaks[end] is None:
            continue
        for start in range(end - 1, -1, -1):
            text = _srt_join((word["word"] for word in words[start:end]), profile)
            duration = words[end - 1]["end"] - words[start]["start"]
            too_long = duration > SRT_MAX_DURATION or not _srt_fits(text, profile)
            if end - start > 1 and too_long and best[end] is not None:
                break  # longer cues cannot fit either; without any cue yet, accept one
            if best[start] is None:
                continue
            fragment = (
                len(words) > end - start and srt_length(text, profile) < profile.line_length / 2
            )
            cost = best[start][0] + 1000 - breaks[end] + 30 * fragment
            if best[end] is None or cost < best[end][0]:
                best[end] = (cost, start)
    cues, end = [], len(words)
    while end:
        start = best[end][1]
        cues.insert(0, words[start:end])
        end = start
    return cues


def srt_cues(segments, language=None):
    """Turns transcript segments into Netflix-style cues of [start, end, text, speaker]."""
    profile = srt_profile(language)
    cues, sentence, speaker = [], [], None

    def flush():
        for words in _srt_split(sentence, profile) if sentence else []:
            text = _srt_join((word["word"] for word in words), profile)
            cues.append([words[0]["start"], words[-1]["end"], text, speaker])
        sentence.clear()

    for segment in segments:
        words = [w for w in segment.get("words") or [] if w.get("start") is not None]
        if not words or segment.get("speaker") != speaker:
            flush()
        speaker = segment.get("speaker")
        if not words:
            text = str(segment["text"]).strip()
            cues.append([segment["start"], segment["end"], text, speaker])
            continue
        for word in words:
            # Segments ending mid-sentence carry over, so cues follow sentences.
            if sentence and _srt_sentence_end(sentence[-1], word, profile):
                flush()
            sentence.append(word)
    flush()

    def merge(previous, cue):
        """Merges cue into previous if both are one speaker's and the result still fits."""
        text = f"{previous[2]}{' ' if profile.spaced else ''}{cue[2]}"
        if (
            previous[3] == cue[3]
            and cue[1] - previous[0] <= SRT_MAX_DURATION
            and _srt_fits(text, profile)
        ):
            previous[1:3] = [cue[1], text]
            return True
        return False

    def too_short(cues, i):
        """Whether cue i cannot stay up for the minimum duration before the next one starts."""
        return (
            i + 1 < len(cues)
            and cues[i + 1][0] - profile.min_gap - cues[i][0] < profile.min_duration
        )

    merged = []
    for cue in cues:
        if not (merged and too_short([merged[-1], cue], 0) and merge(merged[-1], cue)):
            merged.append(cue)
    for i in range(len(merged) - 1, 0, -1):
        # A short cue that cannot take in the next one joins the previous one instead.
        if too_short(merged, i) and merge(merged[i - 1], merged[i]):
            del merged[i]

    for i, cue in enumerate(merged):
        # Hold each cue long enough to read, then close small gaps to the next one.
        reading_time = srt_length(cue[2], profile) / profile.chars_per_second
        end = max(cue[1], cue[0] + max(profile.min_duration, reading_time))
        end = min(end, cue[0] + SRT_MAX_DURATION)
        if i + 1 < len(merged) and merged[i + 1][0] - end < max(
            profile.bridge_gap, profile.min_gap
        ):
            end = min(merged[i + 1][0] - profile.min_gap, cue[0] + SRT_MAX_DURATION)
        cue[1] = max(end, cue[0])
    return merged


def _srt_time(seconds):
    return (
        time.strftime("%H:%M:%S", time.gmtime(seconds))
        + f",{round((seconds - int(seconds)) * 1000):03}"
    )


def srt_document(segments, language=None):
    """Returns the SRT text for transcript segments, following the Netflix subtitle guidelines."""
    profile = srt_profile(language)
    blocks = []
    for index, (start, end, text, _) in enumerate(srt_cues(segments, language), 1):
        text = " ".join(text.replace("...", "…").split())
        lines = "\n".join(srt_wrap(text, profile))
        blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{lines}\n\n")
    return "".join(blocks)

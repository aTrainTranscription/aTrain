"""Netflix-style subtitle cues built from Whisper word timestamps."""

import re
import time
import unicodedata
from dataclasses import dataclass, replace

# Subtitle rules from the Netflix Timed Text Style Guides, linked to their passages below. The
# per-language tables also follow the Netflix quality check of Subtitle Edit
# (https://github.com/SubtitleEdit/subtitleedit, MIT License, Copyright (c) Nikolaj Olsson);
# languages without an entry use the defaults.

# Characters per line, "Character Limitation" in the language guides:
# English I.2 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977#h_01J1EZBGW3CPMYRS1SKDKXQQE6
# German I.3 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217351587#h_01J9KXGXXDQBYEMZXY1W8VWEEE
# Japanese I.5 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517 (no anchors)
# Korean I.2 https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127#h_01HTQ59SEM4V6GSPWFTA3Q3RC8
# Chinese (Simplified) 1 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007#h_01HE8BHXBDQMNX3F1H90C92P74
# Thai I.3 https://partnerhelp.netflixstudios.com/hc/en-us/articles/220448308#h_01FWRFY62RZPMR1030MEWSMR51
SRT_LINE_LENGTH = {"ja": 13, "ko": 16, "th": 35, "zh": 16}
SRT_DEFAULT_LINE_LENGTH = 42
# Characters per second for adult programs, "Reading Speed Limits" in the language guides
# (Arabic and Hindi from Subtitle Edit):
# English I.14 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977#h_02858920-2fd6-4cf5-8c99-01a2216339d7
# German I.16 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217351587#h_01GMTX0DZQE9RWF34H58GD5S1K
# Japanese I.19 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517 (no anchors)
# Korean I.15 https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127#h_01GMWT9GA57R52D95433QQMKRN
# Chinese (Simplified) 14 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007#h_01GMX0AS18VY8KP9VAD2ZJVC86
# Thai I.16 https://partnerhelp.netflixstudios.com/hc/en-us/articles/220448308#h_01GMX1QX9NM6ANBQP211DMMEBX
SRT_CHARS_PER_SECOND = {"ar": 20, "en": 20, "hi": 22, "ja": 4, "ko": 12, "zh": 9}
SRT_DEFAULT_CHARS_PER_SECOND = 17
# Minimum 5/6 s and maximum 7 s per cue, at most two lines, General Requirements 1. Duration and
# 4. Line Treatment:
# https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617#h_01JX10EE4D738M1VTR2JT9JVRD
# https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617#h_01JX10EE4E3X67FZXP3E5G5RZE
# Japanese allows 0.5 s, Japanese guide I.9. Duration (link above).
SRT_MIN_DURATION = 5 / 6
SRT_MIN_DURATION_JA = 0.5
SRT_MAX_DURATION = 7.0
# Two frames between cues, gaps under half a second closed to two frames, Subtitle Timing
# Guidelines 5: Gaps between subtitles:
# https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394#h_01J9KJ62CMHQD9N8Q3WEK0CRT2
SRT_FRAME = 1 / 24
SRT_BRIDGE_GAP = 0.5
# Stay up about half a second after the speech ends, where there is room, Subtitle Timing
# Guidelines 1: Timing to audio:
# https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394#h_01ENQY265MSMNVX6HPH5M71HFD
SRT_LINGER = 0.5
SRT_UNSPACED_LANGUAGES = {"ja", "zh", "th", "lo", "my", "km"}
# Dashes for two speakers in one cue (first line, second line), "Dual Speakers" in the language
# guides; the language table is Subtitle Edit's, other languages use "-" on both lines:
# English I.6 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977#h_2451eb53-33fc-4c00-91cf-8b12e2ce6e27
# German I.7 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217351587#h_01ENX4FPWE60F8VNQN1MKFJ9MJ
# Korean I.6 https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127#h_01ENXC62B7FFW2SXVW0GKPQ5SF
# Chinese (Simplified) 5 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007#h_01EP26NR0K5D7E9EQTFMMSJ9AT
# Thai I.7 https://partnerhelp.netflixstudios.com/hc/en-us/articles/220448308#h_01EP2APQQQ1GGW09YT07MHCFFH
SRT_DIALOG_DASHES = {
    **dict.fromkeys(("ar", "cs", "es", "fr", "hu", "id", "it", "ko", "ms", "pl", "pt", "ro", "ru",
                     "sk", "th", "vi"), ("- ", "- ")),
    **dict.fromkeys(("fi", "he", "nl", "sr"), ("", "-")),
    "bg": ("", "- "),
}  # fmt: skip
# Punctuation a language guide does not allow, replaced by a space, "Punctuation" in the guides:
# Japanese I.17 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517 (no anchors)
# Chinese (Simplified) 12 https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007#h_01HE8BHXBEB2GPJ17RWXCCYWPC
# Thai I.14 https://partnerhelp.netflixstudios.com/hc/en-us/articles/220448308#h_01EE5Y6XF8A190F67C9MBK9MZT
SRT_NO_PUNCTUATION = {"ja": r"[。、]", "th": r"\?|\.(?=\s|$)", "zh": r"[，。,]|\.(?=\s|$)"}  # noqa: RUF001
SRT_PUNCTUATION = (".", ",", "?", "!", ";", ":", "…", "。", "，", "、", "？", "！", "；", "：")  # noqa: RUF001
SRT_SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")  # noqa: RUF001
# Pauses that end a sentence in unpunctuated text, as in Subtitle Edit's "add periods" step
SRT_PAUSE_SENTENCE = 0.6
SRT_PAUSE_ALWAYS = 1.25
SRT_EN_SKIP_LAST = {"with", "however", "a"}
SRT_EN_SKIP_FIRST = {"to", "and", "but", "with", "off", "have"}
# English line breaking: break before these words, never after those, and keep names together,
# English guide I.10. Line Treatment:
# https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977#h_c0a8cf1c-089b-4b6f-94e3-fbb4d03faa2a
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
    """Netflix subtitle rules for one language."""

    language: str
    line_length: int
    chars_per_second: int
    min_duration: float
    min_gap: float
    bridge_gap: float
    spaced: bool
    dashes: tuple
    no_punctuation: str | None
    word_spaces: bool = True  # Whisper starts words with a space; other tokens continue a word


def srt_profile(language):
    """Returns the Netflix subtitle rules for a Whisper language code."""
    language = str(language or "").split("-")[0].lower()
    language = "zh" if language == "yue" else language
    return SrtProfile(
        language=language,
        line_length=SRT_LINE_LENGTH.get(language, SRT_DEFAULT_LINE_LENGTH),
        chars_per_second=SRT_CHARS_PER_SECOND.get(language, SRT_DEFAULT_CHARS_PER_SECOND),
        min_duration=SRT_MIN_DURATION_JA if language == "ja" else SRT_MIN_DURATION,
        min_gap=2 * SRT_FRAME,
        bridge_gap=SRT_BRIDGE_GAP,
        spaced=language not in SRT_UNSPACED_LANGUAGES,
        dashes=SRT_DIALOG_DASHES.get(language, ("-", "-")),
        no_punctuation=SRT_NO_PUNCTUATION.get(language),
    )


def srt_length(text, profile):
    """Counts characters the Netflix way.

    Combining marks, such as Thai tone marks and upper or lower vowels, are not counted. In
    Japanese and Korean, half-width characters, spaces and punctuation count half. See the
    "Character Limitation" links at SRT_LINE_LENGTH.
    """
    half = profile.language in ("ja", "ko")
    return sum(
        0.5 if half and unicodedata.east_asian_width(char) not in ("W", "F") else 1
        for char in text
        if char != "\n" and unicodedata.category(char) != "Mn"
    )


def _srt_units(text, profile):
    """Splits text into the pieces a line can break between: words, or characters with their marks."""
    if profile.spaced:
        return text.split(" ")
    units = []
    for char in text:
        if units and unicodedata.category(char) == "Mn":
            units[-1] += char
        else:
            units.append(char)
    return units


def _srt_join(tokens, profile):
    """Joins word tokens into text."""
    tokens = [str(token) for token in tokens]
    if not profile.spaced or profile.word_spaces:
        return "".join(tokens).strip()
    text = ""
    for token in tokens:
        token = token.strip()
        if text and not token.startswith(SRT_PUNCTUATION):
            text += " "
        text += token
    return text


def _srt_name(previous, following):
    """Whether two words look like parts of one name, which Netflix does not split."""
    return (
        previous[:1].isupper()
        and following[:1].isupper()
        and "I" not in (previous, following)
        and not previous.endswith(SRT_PUNCTUATION)
    )


def srt_wrap(text, profile):
    """Splits text into at most two lines, preferring Netflix-style line breaks."""
    if srt_length(text, profile) <= profile.line_length:
        return [text]
    english = profile.language == "en"
    separator = " " if profile.spaced else ""
    units = _srt_units(text, profile)
    best, best_score = [text], None
    for i in range(1, len(units)):
        top = separator.join(units[:i]).rstrip()
        bottom = separator.join(units[i:]).lstrip()
        if not top or not bottom:
            continue
        previous, following = units[i - 1], units[i]
        top_length, bottom_length = srt_length(top, profile), srt_length(bottom, profile)
        score = abs(top_length - bottom_length)
        score += 100 * (max(top_length, bottom_length) > profile.line_length)
        score += 100 * following.startswith(SRT_PUNCTUATION)
        score += 60 * _srt_name(previous, following)
        if previous.endswith(SRT_PUNCTUATION) or previous.isspace():
            score -= 30
        elif english and following.lower().strip("".join(SRT_PUNCTUATION)) in SRT_EN_BREAK_BEFORE:
            score -= 15
        if english and previous.lower() in SRT_EN_NO_BREAK_AFTER:
            score += 60
        elif english and previous.lower() in SRT_EN_BREAK_BEFORE:
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
    pause = following["start"] - previous["end"]
    if text.endswith(SRT_SENTENCE_END) or pause > SRT_PAUSE_ALWAYS:
        return True
    if text.endswith(SRT_PUNCTUATION) or pause <= SRT_PAUSE_SENTENCE:
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
    token = words[i]["word"]
    if (spaced and not token.startswith(" ")) or unicodedata.category(token[:1] or " ") == "Mn":
        return None  # Whisper starts words with a space; other tokens continue a word
    previous, following = words[i - 1]["word"].strip(), token.strip()
    score = 30 * (previous.endswith(SRT_PUNCTUATION) and not previous.endswith(SRT_SENTENCE_END))
    score += 40 * min(words[i]["start"] - words[i - 1]["end"], 1.0)
    score -= 60 * _srt_name(previous, following)
    if profile.language == "en":
        previous, following = previous.lower(), following.lower()
        score += 15 * (following in SRT_EN_BREAK_BEFORE) - 15 * (previous in SRT_EN_BREAK_BEFORE)
        score -= 60 * (previous in SRT_EN_NO_BREAK_AFTER)
    return score


def _srt_split(words, profile):
    """Splits one sentence into the fewest cues that fit, breaking at the most natural places."""
    spaced = profile.spaced and profile.word_spaces
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


def _srt_words(segment, profile):
    """Returns the timed words of a segment, spreading its time over its words if it has none."""
    words = [w for w in segment.get("words") or [] if w.get("start") is not None]
    text = str(segment.get("text") or "").strip()
    if words or not text:
        return words
    tokens = (
        [f" {token}" for token in text.split()] if profile.spaced else _srt_units(text, profile)
    )
    total, start = sum(len(token) for token in tokens), segment["start"]
    for token in tokens:
        end = start + (segment["end"] - segment["start"]) * len(token) / total
        words.append({"start": start, "end": end, "word": token})
        start = end
    return words


def _srt_combine(previous, cue, profile):
    """Returns two cues as one, on dashed lines for two speakers, or None if they do not fit."""
    if (
        cue[1] - previous[0] > SRT_MAX_DURATION
        or cue[0] - previous[1] > SRT_PAUSE_ALWAYS  # keep cues in sync with the speech
        or "\n" in previous[2] + cue[2]
    ):
        return None
    if previous[3] == cue[3]:
        text = f"{previous[2]}{' ' if profile.spaced else ''}{cue[2]}"
        return [previous[0], cue[1], text, cue[3]] if _srt_fits(text, profile) else None
    lines = [f"{profile.dashes[0]}{previous[2]}", f"{profile.dashes[1]}{cue[2]}"]
    if all(srt_length(line, profile) <= profile.line_length for line in lines):
        return [previous[0], cue[1], "\n".join(lines), (previous[3], cue[3])]
    return None


def _srt_room(cue, next_start, profile):
    """Seconds a cue can stay up before the next cue or the maximum duration."""
    end = cue[0] + SRT_MAX_DURATION
    if next_start is not None:
        end = min(end, next_start - profile.min_gap)
    return end - cue[0]


def _srt_speed(cue, next_start, profile):
    """Characters per second a cue needs when it stays up as long as it can."""
    return srt_length(cue[2], profile) / max(_srt_room(cue, next_start, profile), 0.001)


def _srt_merge(cues, profile):
    """Merges cues too short or too fast to read into a neighbour, where the result still fits."""

    def next_start(cues, i):
        return cues[i + 1][0] if i + 1 < len(cues) else None

    def too_short(cues, i):
        return _srt_room(cues[i], next_start(cues, i), profile) < profile.min_duration

    merged = []
    for cue in cues:
        combined = (
            merged and too_short([merged[-1], cue], 0) and _srt_combine(merged[-1], cue, profile)
        )
        if combined:
            merged[-1] = combined
        else:
            merged.append(cue)
    for i in range(len(merged) - 1, 0, -1):
        # A short cue that cannot take in the next one joins the previous one instead.
        combined = too_short(merged, i) and _srt_combine(merged[i - 1], merged[i], profile)
        if combined:
            merged[i - 1 : i + 1] = [combined]
    i = 0
    while i + 1 < len(merged):
        # Merge neighbours that are too fast to read when the merged cue reads slower.
        speed = max(_srt_speed(merged[j], next_start(merged, j), profile) for j in (i, i + 1))
        combined = speed > profile.chars_per_second and _srt_combine(
            merged[i], merged[i + 1], profile
        )
        if combined and _srt_speed(combined, next_start(merged, i + 1), profile) < speed:
            merged[i : i + 2] = [combined]
        else:
            i += 1
    return merged


def srt_cues(segments, language=None):
    """Turns transcript segments into Netflix-style cues of [start, end, text, speaker].

    The text of a cue shared by two speakers holds their two dashed lines.
    """
    profile = srt_profile(language)
    # Whisper words start with a space and tokens without one continue a word; other backends
    # give whole words without spaces. Decided once, as a cue may hold only continuation tokens.
    tokens = [str(w.get("word", "")) for s in segments for w in s.get("words") or []]
    profile = replace(profile, word_spaces=not tokens or any(t.startswith(" ") for t in tokens))
    cues, sentence, speaker = [], [], None

    def flush():
        for words in _srt_split(sentence, profile) if sentence else []:
            text = _srt_join((word["word"] for word in words), profile)
            cues.append([words[0]["start"], words[-1]["end"], text, speaker])
        sentence.clear()

    for segment in segments:
        for word in _srt_words(segment, profile):
            word_speaker = word.get("speaker", segment.get("speaker"))
            # A new speaker or sentence starts a new cue; segments ending mid-sentence carry over.
            if sentence and (
                word_speaker != speaker or _srt_sentence_end(sentence[-1], word, profile)
            ):
                flush()
            speaker = word_speaker
            sentence.append(word)
    flush()

    cues = _srt_merge(cues, profile)
    for i, cue in enumerate(cues):
        # Hold each cue long enough to read and a little past the speech, then close small gaps.
        reading_time = srt_length(cue[2], profile) / profile.chars_per_second
        end = max(cue[1] + SRT_LINGER, cue[0] + max(profile.min_duration, reading_time))
        end = min(end, cue[0] + SRT_MAX_DURATION)
        if i + 1 < len(cues) and cues[i + 1][0] - end < profile.bridge_gap:
            end = min(cues[i + 1][0] - profile.min_gap, cue[0] + SRT_MAX_DURATION)
        cue[1] = max(end, cue[0])
    return cues


def _srt_time(seconds):
    return (
        time.strftime("%H:%M:%S", time.gmtime(seconds))
        + f",{round((seconds - int(seconds)) * 1000):03}"
    )


def _srt_clean(text, profile):
    """Applies the language's punctuation rules and removes extra white space."""
    text = text.replace("...", "…")  # English guide I.12. Punctuation, and the other guides
    if profile.no_punctuation:
        text = re.sub(profile.no_punctuation, " ", text)
    return " ".join(text.split())


def srt_document(segments, language=None):
    """Returns the SRT text for transcript segments, following the Netflix subtitle guidelines."""
    profile = srt_profile(language)
    blocks = []
    for start, end, text, _ in srt_cues(segments, language):
        if "\n" in text:
            lines = [_srt_clean(line, profile) for line in text.split("\n")]
        else:
            lines = srt_wrap(_srt_clean(text, profile), profile)
        lines = "\n".join(line for line in lines if line)
        if lines:  # punctuation-only cues are empty once the punctuation is removed
            index = len(blocks) + 1
            blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{lines}\n\n")
    return "".join(blocks)


def _srt_seconds(timestamp):
    hours, minutes, rest = timestamp.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def parse_srt(document):
    """Returns the (start, end, lines) of every cue in an SRT document."""
    cues = []
    for block in document.strip().split("\n\n") if document.strip() else []:
        lines = block.split("\n")
        start, end = lines[1].split(" --> ")
        cues.append((_srt_seconds(start), _srt_seconds(end), lines[2:]))
    return cues


def netflix_issues(document, language=None):
    """Returns (rule, cue number) for every Netflix rule an SRT document breaks.

    Ports the checks of Subtitle Edit's Netflix quality check that apply to audio-only output.
    Shot changes need the video, and italics or number spelling would change the transcript.
    """
    profile = srt_profile(language)
    cues, issues = parse_srt(document), []
    for index, (start, end, lines) in enumerate(cues):
        number, duration, text = index + 1, end - start, "".join(lines)
        if any(srt_length(line, profile) > profile.line_length for line in lines):
            issues.append(("max line length", number))
        if len(lines) > 2:
            issues.append(("two lines maximum", number))
        dialog = len(lines) == 2 and lines[1].startswith("-")
        if (
            len(lines) == 2
            and not dialog
            and srt_length(" ".join(lines), profile) <= profile.line_length
        ):
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

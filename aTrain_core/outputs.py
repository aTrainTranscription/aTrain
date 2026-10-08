import json
import os
import shutil
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from aTrain_core.backends.common import SRT_MAX_DURATION, ends_sentence, group_word_segments
from aTrain_core.globals import (
    LOG_FILENAME,
    METADATA_FILENAME,
    TIMESTAMP_FORMAT,
    TRANSCRIPT_DIR,
    write_json_atomic,
)
from aTrain_core.settings import Settings


def create_file_id(file_path, timestamp):
    """Creates a unique identifier for a file composed of the file path and timestamp."""
    # Extract filename from file_path
    file_base_name = os.path.basename(file_path)
    # Use rsplit to split from the right at most once

    timestamp = timestamp.replace(" ", "-").replace("-", "")
    timestamp = timestamp[:-2]
    timestamp = timestamp[2:]

    short_base_name = file_base_name[0:7] if len(file_base_name) >= 5 else file_base_name
    file_id = timestamp + "-" + short_base_name
    return file_id


def free_file_id(file_path, timestamp) -> str:
    """A file_id no archive folder has yet. Adds -2, -3, ... in the same minute."""
    base_file_id = create_file_id(file_path, timestamp)
    file_id, suffix = base_file_id, 1
    while os.path.exists(os.path.join(TRANSCRIPT_DIR, file_id)):
        suffix += 1
        file_id = f"{base_file_id}-{suffix}"
    return file_id


def claim_file_id(file_path, timestamp) -> str:
    """Create a new archive folder and return its file_id, so two transcriptions never
    share one (also across processes)."""
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    while True:
        file_id = free_file_id(file_path, timestamp)
        with suppress(FileExistsError):
            os.makedirs(os.path.join(TRANSCRIPT_DIR, file_id))
            return file_id


PENDING_DIR = ".pending"  # hidden in the archive: outputs are written here, then published


def fresh_output_dir(file_id: str) -> Path:
    """An output folder hidden in the archive, so publish() can move it in with one rename
    on the same file system. Removes what an interrupted attempt left in .pending."""
    pending = Path(TRANSCRIPT_DIR) / PENDING_DIR
    shutil.rmtree(pending, ignore_errors=True)
    return pending / file_id


def publish(directory: Path) -> None:
    """Move a complete output folder (from fresh_output_dir) into the archive in one step,
    so the archive never shows a half-written transcription. Its name is its file_id."""
    target = Path(TRANSCRIPT_DIR) / directory.name
    if target.exists():
        raise FileExistsError(f"The archive already has a folder {directory.name}")
    os.rename(directory, target)


def create_output_files(result, speaker_detection, directory: Path, subtitles=None):
    """Creates output files based on the transcription result."""
    create_json_file(result, directory)
    create_txt_file(
        result, directory, speaker_detection, maxqda=False, timestamps=False, brackets=True
    )
    create_txt_file(
        result, directory, speaker_detection, maxqda=False, timestamps=True, brackets=True
    )
    create_txt_file(
        result, directory, speaker_detection, maxqda=False, timestamps=True, brackets=False
    )  # NEW: NVivo output format
    create_txt_file(
        result, directory, speaker_detection, maxqda=True, timestamps=True, brackets=True
    )
    create_srt_file(subtitles or result, directory)


def create_json_file(result, directory: Path):
    """Creates a JSON file for the transcription result."""
    output_file_text = directory / "transcription.json"
    with open(output_file_text, "w", encoding="utf-8") as json_file:
        json.dump(result, json_file, ensure_ascii=False)


def create_txt_file(result, directory: Path, speaker_detection, timestamps, maxqda, brackets=True):
    """Creates a TXT file for the transcription result."""
    segments = result["segments"]
    match maxqda, timestamps, brackets:
        case True, _, _:
            filename = "transcription_maxqda.txt"
        case False, True, False:
            filename = "transcription_nvivo.txt"  # NVivo format: timestamps without brackets
        case False, True, True:
            filename = "transcription_timestamps.txt"
        case False, False, _:
            filename = "transcription.txt"
    file_path = directory / filename
    with open(file_path, "w", encoding="utf-8") as file:
        headline = (
            f"Transcription for {directory.name}"
            + ("" if maxqda and speaker_detection else "\n")
            + ("" if speaker_detection else "\n")
        )
        file.write(headline)
        current_speaker = None
        for segment in segments:
            speaker = segment["speaker"] if "speaker" in segment else "Speaker undefined"
            if speaker != current_speaker and speaker_detection:
                file.write(("\n\n" if maxqda else "\n") + speaker + "\n")
                current_speaker = speaker
            text = str(segment["text"]).lstrip()
            if timestamps:
                start_time = time.strftime("[%H:%M:%S]", time.gmtime(segment["start"]))
                text = f"{start_time} - {text}"
            file.write(text + (" " if maxqda else "\n"))


def create_srt_file(result, directory: Path):
    """Creates a SRT file for the transcription result."""

    segments = result["segments"]
    file_path = directory / "transcription.srt"
    with open(file_path, "w", encoding="utf-8") as srt_file:
        for index, segment in enumerate(segments, 1):
            srt_file.write(f"{index}\n")
            start_time = segment["start"]
            end_time = segment["end"]
            start_time_format = (
                time.strftime("%H:%M:%S", time.gmtime(start_time))
                + f",{round((start_time - int(start_time)) * 1000):03}"
            )
            end_time_format = (
                time.strftime("%H:%M:%S", time.gmtime(end_time))
                + f",{round((end_time - int(end_time)) * 1000):03}"
            )
            srt_file.write(f"{start_time_format} --> {end_time_format}\n")
            srt_file.write(f"{str(segment['text']).lstrip()}\n\n")


def transform_speakers_results(diarization_segments):
    """Transforms diarization segments to speaker results."""

    diarize_df = pd.DataFrame(diarization_segments.itertracks(yield_label=True))
    diarize_df["start"] = diarize_df[0].apply(lambda x: x.start)
    diarize_df["end"] = diarize_df[0].apply(lambda x: x.end)
    diarize_df.rename(columns={2: "speaker"}, inplace=True)
    return diarize_df


def create_metadata(settings: Settings, audio_duration: int, directory: Path | None = None):
    """Creates metadata file for the transcription, by default in its archive folder."""

    directory = directory or Path(TRANSCRIPT_DIR) / settings.file_id
    metadata_file_path = directory / METADATA_FILENAME
    metadata = {
        "file_id": settings.file_id,
        "filename": settings.file_name,
        "audio_duration": audio_duration,
        "model": settings.model,
        "language": settings.language,
        "speaker_detection": settings.speaker_detection,
        "num_speakers": settings.speaker_count,
        "device": settings.device.value,
        "compute_type": settings.compute_type.value,
        "timestamp": settings.timestamp,
    }
    with open(metadata_file_path, "w", encoding="utf-8") as metadata_file:
        yaml.dump(metadata, metadata_file)
    make_logger(directory / LOG_FILENAME)("Metadata created")


def write_logfile(message, file_id):
    """Writes a log message to the log file."""

    make_logger(Path(TRANSCRIPT_DIR) / file_id / LOG_FILENAME)(message)


def make_logger(log_file: Path) -> Callable[[str], None]:
    """Return a function that appends timestamped messages to log_file."""

    def log(message: str) -> None:
        timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] ------ {message}\n")

    return log


def add_processing_time_to_metadata(directory: Path):
    """Adds processing time information to metadata."""

    metadata_file_path = directory / METADATA_FILENAME
    with open(metadata_file_path, encoding="utf-8") as metadata_file:
        metadata = yaml.safe_load(metadata_file)
    timestamp = metadata["timestamp"]
    start_time = datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    stop_time = timestamp = datetime.now()
    processing_time = stop_time - start_time
    metadata["processing_time"] = int(processing_time.total_seconds())
    with open(metadata_file_path, "w", encoding="utf-8") as metadata_file:
        yaml.dump(metadata, metadata_file)


def finalize(transcript: dict, backend: str) -> tuple[dict, dict]:
    """Group the word segments into output cues, and into shorter cues for subtitles.
    Runs after speaker detection, because a speaker change starts a new cue."""

    join_raw = backend != "crisper-transformers"
    segments = transcript["segments"]
    cues = {"segments": group_word_segments(segments, join_raw)}
    subtitles = {"segments": group_word_segments(segments, join_raw, max_duration=SRT_MAX_DURATION)}
    return cues, subtitles


def write_final_outputs(
    settings: Settings,
    transcript: dict,
    *,
    audio_duration: int,
    backend: str,
    work_log: Path | None = None,
    export_dir: Path | None = None,
    directory: Path | None = None,
) -> list[str]:
    """Write metadata, log and all output files into `directory` (its name is
    settings.file_id; by default the archive folder), then the optional copy to
    export_dir/<file_id>. Returns warnings: a failed copy is never an error, the result
    is in the archive anyway."""

    file_id = settings.file_id
    directory = directory or Path(TRANSCRIPT_DIR) / file_id
    directory.mkdir(parents=True, exist_ok=True)
    log = make_logger(directory / LOG_FILENAME)
    if work_log is not None:
        shutil.copyfile(work_log, directory / LOG_FILENAME)
    if not (directory / METADATA_FILENAME).exists():
        create_metadata(settings, audio_duration, directory)
    cues, subtitles = finalize(transcript, backend)
    create_output_files(cues, settings.speaker_detection, directory, subtitles)
    log("Created output files")
    add_processing_time_to_metadata(directory)
    log("Processing time added to metadata")
    if export_dir is None:
        return []
    target = Path(export_dir) / file_id
    try:
        shutil.copytree(directory, target, dirs_exist_ok=True)
    except OSError as e:
        warning = f"Copy to {target} failed: {e}"
        log(warning)
        return [warning]
    return []


@dataclass(frozen=True, slots=True)
class Checkpoint:
    transcript: dict
    audio_duration: int


def write_checkpoint(
    path: Path,
    *,
    transcript: dict,
    audio_duration: int,
    source: Path,
    source_stat: os.stat_result | None = None,
) -> None:
    """Save a word-level transcript atomically, tied to the size and modification time
    of the source it was made from (`source_stat`, taken before decoding; default: now)."""

    stat = source_stat or os.stat(source)
    data = {
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "audio_duration": audio_duration,
        "transcript": transcript,
    }
    write_json_atomic(path, data)


def read_checkpoint(
    path: Path, source: Path, source_stat: os.stat_result | None = None
) -> Checkpoint | None:
    """Return the saved transcript, or None if the file is missing or damaged, or the
    source is gone or has changed since the checkpoint was written. Compares against
    `source_stat` if given, else against the source now."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stat = source_stat or os.stat(source)
        if (data["source_size"], data["source_mtime_ns"]) != (stat.st_size, stat.st_mtime_ns):
            return None
        return Checkpoint(data["transcript"], data["audio_duration"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def delete_transcription(file_id):
    """Deletes the transcription files."""

    file_id = "" if file_id == "all" else file_id
    directory_name = os.path.join(TRANSCRIPT_DIR, file_id)
    if os.path.exists(directory_name):
        shutil.rmtree(directory_name)
    if not os.path.exists(TRANSCRIPT_DIR):
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)


def assign_word_speakers(diarize_df, transcript_result, fill_nearest=False):
    """Assigns speakers to transcribed words.
    Function is taken from whisperx -> see https://github.com/m-bain/whisperX.git
    """
    transcript_segments = transcript_result["segments"]
    for seg in transcript_segments:
        if "words" in seg:
            for word in seg["words"]:
                if "start" in word:
                    diarize_df["intersection"] = np.minimum(
                        diarize_df["end"], word["end"]
                    ) - np.maximum(diarize_df["start"], word["start"])
                    dia_tmp = (
                        diarize_df[diarize_df["intersection"] > 0]
                        if not fill_nearest
                        else diarize_df
                    )
                    at_onset = dia_tmp[
                        (dia_tmp["start"] <= word["start"]) & (dia_tmp["end"] > word["start"])
                    ]
                    if len(at_onset) > 0:
                        dia_tmp = at_onset
                    if len(dia_tmp) > 0:
                        speaker = (
                            dia_tmp.groupby("speaker")["intersection"]
                            .sum()
                            .sort_values(ascending=False, kind="stable")
                            .index[0]
                        )
                        word["speaker"] = speaker
            durations = {}
            for word in seg["words"]:
                if "speaker" in word:
                    duration = word["end"] - word["start"]
                    durations[word["speaker"]] = durations.get(word["speaker"], 0) + duration
            if durations:
                seg["speaker"] = max(durations, key=durations.get)
        # Fall back to the segment's own overlap when no word got a speaker.
        if "speaker" not in seg:
            diarize_df["intersection"] = np.minimum(diarize_df["end"], seg["end"]) - np.maximum(
                diarize_df["start"], seg["start"]
            )
            dia_tmp = diarize_df[diarize_df["intersection"] > 0] if not fill_nearest else diarize_df
            if len(dia_tmp) > 0:
                speaker = (
                    dia_tmp.groupby("speaker")["intersection"]
                    .sum()
                    .sort_values(ascending=False, kind="stable")
                    .index[0]
                )
                seg["speaker"] = speaker
    # Segments overlapping no speaker turn take the speaker of the nearest turn.
    if len(diarize_df) > 0:
        for seg in transcript_segments:
            if "speaker" not in seg:
                distance = np.maximum(
                    diarize_df["start"] - seg["end"], seg["start"] - diarize_df["end"]
                )
                seg["speaker"] = diarize_df.loc[distance.idxmin(), "speaker"]
                for word in seg.get("words", []):
                    word.setdefault("speaker", seg["speaker"])
    return transcript_result


def smooth_speaker_flips(segments, max_segments=2, max_gap=1.0):
    """Give short speaker runs the majority speaker of their sentence.

    A sentence ends at sentence punctuation or at a pause of max_gap or more. A run of up to
    max_segments is relabeled when another speaker holds more of the sentence's duration.
    """
    sentence = []
    for index, seg in enumerate(segments):
        sentence.append(seg)
        if (
            index + 1 == len(segments)
            or ends_sentence(seg["text"])
            or segments[index + 1]["start"] - seg["end"] >= max_gap
        ):
            _relabel_short_runs(sentence, max_segments)
            sentence = []
    return segments


def _relabel_short_runs(sentence, max_segments):
    """Relabel a sentence's short minority speaker runs to its majority speaker."""
    durations = {}
    for seg in sentence:
        speaker = seg.get("speaker")
        durations[speaker] = durations.get(speaker, 0) + seg["end"] - seg["start"]
    majority = max(durations, key=durations.get)
    i = 0
    while i < len(sentence):
        speaker = sentence[i].get("speaker")
        j = i
        while j + 1 < len(sentence) and sentence[j + 1].get("speaker") == speaker:
            j += 1
        if j - i + 1 <= max_segments and durations[speaker] < durations[majority]:
            for seg in sentence[i : j + 1]:
                seg["speaker"] = majority
                for word in seg.get("words", []):
                    word["speaker"] = majority
        i = j + 1

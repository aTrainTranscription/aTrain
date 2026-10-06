"""Tests for the output steps in aTrain_core.outputs: unique file ids,
write_final_outputs and checkpoints."""

import os
from pathlib import Path

import pytest
import yaml
from aTrain_core import outputs
from aTrain_core.settings import ComputeType, Device, Settings

OUTPUT_FILES = {
    "transcription.json",
    "transcription.txt",
    "transcription_timestamps.txt",
    "transcription_nvivo.txt",
    "transcription_maxqda.txt",
    "transcription.srt",
}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "TRANSCRIPT_DIR", tmp_path / "transcriptions")
    return tmp_path / "transcriptions"


def make_settings(file_id: str, speaker_detection: bool) -> Settings:
    return Settings(
        file=Path("interview.mp3"),
        file_id=file_id,
        file_name="interview.mp3",
        model="tiny",
        language="en",
        speaker_detection=speaker_detection,
        speaker_count=None,
        device=Device.CPU,
        compute_type=ComputeType.INT8,
        timestamp="2026-09-30 14-05-12",
        temperature=None,
    )


def transcript(speakers: bool) -> dict:
    words = [
        (" Hello", 0.0, 0.4, "SPEAKER_00"),
        (" there.", 0.5, 1.0, "SPEAKER_00"),
        (" Hi.", 4.0, 4.5, "SPEAKER_01"),
    ]
    segments = []
    for text, start, end, speaker in words:
        segment = {
            "start": start,
            "end": end,
            "text": text.strip(),
            "words": [{"word": text, "start": start, "end": end}],
        }
        if speakers:
            segment["speaker"] = speaker
        segments.append(segment)
    return {"segments": segments}


def test_claim_file_id_adds_suffix_in_the_same_minute(archive):
    first = outputs.claim_file_id(Path("interview_01.mp3"), "2026-09-30 14-05-12")
    second = outputs.claim_file_id(Path("interview_02.mp3"), "2026-09-30 14-05-40")
    assert first == "2609301405-intervi"
    assert second == "2609301405-intervi-2"
    assert (archive / first).is_dir() and (archive / second).is_dir()


@pytest.mark.parametrize("speaker_detection", [True, False])
def test_write_final_outputs_writes_all_files(archive, tmp_path, speaker_detection):
    file_id = outputs.claim_file_id(Path("interview.mp3"), "2026-09-30 14-05-12")
    work_log = tmp_path / "work.log"
    work_log.write_text("[x] ------ Transcription successful\n", encoding="utf-8")

    warnings = outputs.write_final_outputs(
        make_settings(file_id, speaker_detection),
        transcript(speaker_detection),
        audio_duration=5,
        backend="faster-whisper",
        work_log=work_log,
    )

    directory = archive / file_id
    assert warnings == []
    assert {p.name for p in directory.iterdir()} >= OUTPUT_FILES
    text = (directory / "transcription.txt").read_text(encoding="utf-8")
    assert ("SPEAKER_01" in text) is speaker_detection
    metadata = yaml.safe_load((directory / "metadata.txt").read_text(encoding="utf-8"))
    assert metadata["audio_duration"] == 5 and "processing_time" in metadata
    log = (directory / "log.txt").read_text(encoding="utf-8")
    assert log.startswith("[x] ------ Transcription successful") and "Created output files" in log


def test_write_final_outputs_export_copy(archive, tmp_path):
    file_id = outputs.claim_file_id(Path("interview.mp3"), "2026-09-30 14-05-12")
    export_dir = tmp_path / "Interviews" / "transcriptions"
    outputs.write_final_outputs(
        make_settings(file_id, False),
        transcript(False),
        audio_duration=5,
        backend="faster-whisper",
        export_dir=export_dir,
    )
    assert {p.name for p in (export_dir / file_id).iterdir()} >= OUTPUT_FILES


def test_write_final_outputs_failed_copy_is_a_warning(archive, tmp_path):
    file_id = outputs.claim_file_id(Path("interview.mp3"), "2026-09-30 14-05-12")
    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x")
    warnings = outputs.write_final_outputs(
        make_settings(file_id, False),
        transcript(False),
        audio_duration=5,
        backend="faster-whisper",
        export_dir=not_a_folder,
    )
    assert len(warnings) == 1 and warnings[0].startswith("Copy to")
    assert (archive / file_id / "transcription.txt").is_file()


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "interview.mp3"
    path.write_bytes(b"audio")
    return path


def test_checkpoint_round_trip(tmp_path, source):
    path = tmp_path / "work" / "raw_transcript.json"
    outputs.write_checkpoint(path, transcript=transcript(True), audio_duration=5, source=source)
    checkpoint = outputs.read_checkpoint(path, source)
    assert checkpoint == outputs.Checkpoint(transcript(True), 5)
    assert not path.with_name("raw_transcript.json.tmp").exists()


def test_checkpoint_invalid_cases(tmp_path, source):
    path = tmp_path / "raw_transcript.json"
    assert outputs.read_checkpoint(path, source) is None  # missing

    outputs.write_checkpoint(path, transcript=transcript(False), audio_duration=5, source=source)
    path.write_text(path.read_text()[:20])  # truncated
    assert outputs.read_checkpoint(path, source) is None

    outputs.write_checkpoint(path, transcript=transcript(False), audio_duration=5, source=source)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))  # edited
    assert outputs.read_checkpoint(path, source) is None

    outputs.write_checkpoint(path, transcript=transcript(False), audio_duration=5, source=source)
    source.write_bytes(b"other audio")  # replaced
    assert outputs.read_checkpoint(path, source) is None

    outputs.write_checkpoint(path, transcript=transcript(False), audio_duration=5, source=source)
    source.unlink()  # gone
    assert outputs.read_checkpoint(path, source) is None


def test_checkpoint_is_tied_to_the_given_source_stat(tmp_path, source):
    """A checkpoint of audio decoded earlier is tied to the source as it was then."""
    path = tmp_path / "raw_transcript.json"
    decoded_from = source.stat()
    source.write_bytes(b"other audio")  # replaced while the old audio was transcribed

    outputs.write_checkpoint(
        path,
        transcript=transcript(False),
        audio_duration=5,
        source=source,
        source_stat=decoded_from,
    )

    assert outputs.read_checkpoint(path, source) is None
    assert outputs.read_checkpoint(path, source, source_stat=decoded_from) is not None

"""End-to-end: three copies of the fixture through real phase children (tiny model, CPU),
compared with the single-file CLI."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from aTrain_core import runner
from aTrain_core.globals import DEFAULT_CPU_THREADS, TIMESTAMP_FORMAT
from aTrain_core.settings import ComputeType, Device
from tests.core.test_runner_process import drive
from tests.unit.test_jobs import make_spec

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"
OUTPUT_FILES = ["transcription.json", "transcription.txt", "transcription.srt", "metadata.txt"]


def cli(env, *args):
    result = subprocess.run(
        [sys.executable, "-m", "aTrain_core", *args], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("atrain")
    cli({**os.environ, "ATRAIN_USER_DIR": str(data_dir)}, "load", "tiny")
    return data_dir


def spec(source: Path, speaker_detection: bool):
    return make_spec(
        id=source.stem,
        source=source,
        display_name=source.name,
        model="tiny",
        language="auto-detect",
        device=Device.CPU,
        compute_type=ComputeType.INT8,
        cpu_threads=DEFAULT_CPU_THREADS,
        speaker_detection=speaker_detection,
        speaker_count=None,
        export_dir=None,
    )


def segments(directory: Path) -> list:
    return json.loads((directory / "transcription.json").read_text(encoding="utf-8"))["segments"]


def test_jobs_match_single_file_runs(data_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("ATRAIN_USER_DIR", str(data_dir))
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    jobs = []
    for name, speakers in (("aaa", True), ("bbb", True), ("ccc", False)):
        source = tmp_path / f"{name}.mp3"
        shutil.copy(FIXTURE, source)
        jobs.append(runner.PhaseJob(spec(source, speakers), timestamp, tmp_path / "work" / name))

    phase1 = [e for job in jobs for e in asyncio.run(drive(runner.launch_phase1(job)))]
    phase2 = [e for job in jobs[:2] for e in asyncio.run(drive(runner.launch_phase2(job)))]

    assert [
        type(e).__name__
        for e in phase1 + phase2
        if isinstance(e, runner.JobFailed | runner.PhaseDied)
    ] == []
    file_ids = {e.job_id: e.file_id for e in phase1 + phase2 if isinstance(e, runner.JobDone)}
    assert sorted(file_ids) == ["aaa", "bbb", "ccc"]
    archive = data_dir / "transcriptions"
    for file_id in file_ids.values():
        assert all((archive / file_id / name).is_file() for name in OUTPUT_FILES)

    # the same recordings through the normal single-file path
    common = ["--model", "tiny", "--device", "cpu", "--language", "auto-detect"]
    common += ["--cpu-threads", str(DEFAULT_CPU_THREADS)]
    for job_id, extra in (("aaa", ["--speaker-detection"]), ("ccc", [])):
        single = tmp_path / "single" / f"{job_id}.mp3"
        single.parent.mkdir(exist_ok=True)
        shutil.copy(FIXTURE, single)
        before = set(archive.iterdir())
        cli(
            {**os.environ, "ATRAIN_USER_DIR": str(data_dir)},
            "transcribe",
            str(single),
            *common,
            *extra,
        )
        (single_dir,) = set(archive.iterdir()) - before
        assert segments(archive / file_ids[job_id]) == segments(single_dir)

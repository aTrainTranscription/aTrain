"""Tests for the aTrain_core command line interface."""

import pytest
from aTrain_core import cli, outputs
from typer.testing import CliRunner


@pytest.mark.parametrize(
    ("name", "sanitised"),
    [
        ("my interview (1).mp3", "my_interview_1.mp3"),
        ("Gespräch #3.mp3", "Gesprach_3.mp3"),
        ("интервью.mp3", "mp3"),
    ],
)
@pytest.mark.parametrize("sanitised_file_exists", [False, True])
def test_transcribe_uses_the_given_file(
    tmp_path, monkeypatch, name, sanitised, sanitised_file_exists
):
    monkeypatch.setattr(outputs, "TRANSCRIPT_DIR", tmp_path / "transcriptions")
    seen = []
    monkeypatch.setattr(cli, "_transcribe", seen.append)
    audio = tmp_path / name
    audio.write_bytes(b"audio")
    if sanitised_file_exists:
        (tmp_path / sanitised).write_bytes(b"other audio")

    result = CliRunner().invoke(cli.cli, ["transcribe", str(audio)])

    assert result.exit_code == 0, result.output
    [settings] = seen
    assert settings.file == audio
    assert settings.file_name == name

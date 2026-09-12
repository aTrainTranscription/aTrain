"""End-to-end accuracy tests for the transcription pipeline.

Calculate Word Error Rate (WER) for a longer clip against a reference transcript.

Clip:
Transcript:

"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import jiwer
import pytest

WER_TRANSFORM = jiwer.Compose(
    [
        jiwer.ToLowerCase(),
        jiwer.ExpandCommonEnglishContractions(),
        jiwer.SubstituteRegexes({r"-": " "}),  # "medium-term" → "medium term"
        jiwer.RemovePunctuation(),
        jiwer.SubstituteRegexes({r"\s+": " "}),  # collapse newlines/tabs too, not just spaces
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
WER_AUDIO = FIXTURES_DIR / "wer_lagarde.mp3"
WER_REF = FIXTURES_DIR / "reference.txt"


def _run(args, env):
    return subprocess.run(
        [sys.executable, "-m", "aTrain_core", *args],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def atrain_env(tmp_path_factory):
    """Isolated aTrain data dir with the large-v3-turbo model preloaded."""
    data_dir = tmp_path_factory.mktemp("atrain_wer")
    env = {**os.environ, "ATRAIN_USER_DIR": str(data_dir)}
    result = _run(["load", "large-v3-turbo"], env)
    assert result.returncode == 0, f"large-v3-turbo model download failed:\n{result.stderr}"
    return env, data_dir


def _transcribe(env, data_dir, label, fixture_path, *extra_args):
    """Transcribe a uniquely named copy of the fixture; return its output dir."""
    clip = data_dir / f"{label}.mp3"
    shutil.copy(fixture_path, clip)
    transcriptions = data_dir / "transcriptions"
    before = set(transcriptions.glob("*")) if transcriptions.exists() else set()
    result = _run(
        [
            "transcribe",
            str(clip),
            "--model",
            "large-v3-turbo",
            "--device",
            "cpu",
            "--language",
            "auto-detect",
            *extra_args,
        ],
        env,
    )
    assert result.returncode == 0, f"transcription failed:\n{result.stderr}"
    new = [d for d in set(transcriptions.glob("*")) - before if d.is_dir()]
    assert len(new) == 1, f"expected exactly one new output dir, got {new}"
    return new[0]


def test_transcription_accuracy_wer(atrain_env):
    """Calculate Word Error Rate (WER) for a longer clip."""
    env, data_dir = atrain_env
    reference = WER_REF.read_text()

    wers = []
    passed = False
    try:
        for attempt in range(1, 4):
            out = _transcribe(env, data_dir, f"accuracy_attempt_{attempt}", WER_AUDIO)
            # Drop the "Transcription for <id>" header line; the rest is the transcript.
            lines = (out / "transcription.txt").read_text().splitlines()
            hypothesis = "\n".join(lines[2:])

            wer = jiwer.wer(
                reference,
                hypothesis,
                reference_transform=WER_TRANSFORM,
                hypothesis_transform=WER_TRANSFORM,
            )
            wers.append(wer)
            print(f"Attempt {attempt} WER: {wer:.6f} ({wer:.2%})")

            assert wer < 0.12, (
                f"Attempt {attempt} exceeded the 12% maximum WER threshold: {wer:.2%}"
            )

            if wer < 0.05:
                passed = True
                break

        print(f"Total runs required: {len(wers)}")
        print(f"Achieved WER rates: {', '.join(f'{w:.2%}' for w in wers)}")
        assert passed, (
            f"All 3 attempts exceeded the 5% WER threshold. WERs: {', '.join(f'{w:.2%}' for w in wers)}"
        )

    finally:
        # Write to GitHub Actions summary if running in CI
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path and wers:
            try:
                with open(summary_path, "a") as f:
                    f.write("### 📊 E2E WER Test Results\n")
                    f.write(f"- **Total Runs Required:** {len(wers)}\n")
                    f.write(f"- **Achieved WER Rates:** {', '.join(f'{w:.2%}' for w in wers)}\n")
                    if not passed:
                        if any(w >= 0.12 for w in wers):
                            f.write(
                                "- **Status:** ❌ FAILED (Exceeded the 12% maximum WER threshold)\n"
                            )
                        else:
                            f.write(
                                "- **Status:** ❌ FAILED (All attempts exceeded the 5% target threshold)\n"
                            )
                    elif len(wers) > 1:
                        f.write(
                            f"- **Status:** ⚠️ PASSED on attempt {len(wers)} (previous runs exceeded the 5% threshold)\n"
                        )
                    else:
                        f.write("- **Status:**  PASSED on first attempt\n")
            except Exception as e:
                print(f"Warning: Failed to write to GITHUB_STEP_SUMMARY: {e}")

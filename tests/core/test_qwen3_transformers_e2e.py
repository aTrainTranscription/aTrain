"""Real native Qwen3 ASR and separate forced alignment on CPU.

Set ATRAIN_TEST_QWEN=1 to download the pinned 0.6B ASR and the shared aligner
into a temporary directory, or ATRAIN_QWEN_MODEL_ROOT to reuse an aTrain models
directory that contains both. The 1.7B size runs the same code path.
"""

import gc
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
pytestmark = pytest.mark.skipif(
    not (os.environ.get("ATRAIN_TEST_QWEN") == "1" or os.environ.get("ATRAIN_QWEN_MODEL_ROOT")),
    reason="set ATRAIN_TEST_QWEN=1 or ATRAIN_QWEN_MODEL_ROOT for real Qwen3 inference",
)
MODEL = "qwen3-asr-0.6b"


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    # The CLI test writes its transcriptions next to this directory.
    root = tmp_path_factory.mktemp("qwen") / "models"
    if local := os.environ.get("ATRAIN_QWEN_MODEL_ROOT"):
        root.symlink_to(Path(local).resolve(), target_is_directory=True)
        return root

    from aTrain_core import load_resources

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(load_resources, "MODELS_DIR", root)
        load_resources.get_model(MODEL)
    return root


def transcribe(model_dir, clip, seconds, *, language="en", prompt=None):
    import torch
    from aTrain_core.backends import qwen3_transformers
    from aTrain_core.settings import ComputeType, Device, Settings
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(FIXTURES / clip))[: int(seconds * 16000)]
    settings = Settings(
        file=FIXTURES / clip,
        file_id="qwen_test",
        file_name=clip,
        model=MODEL,
        language=language,
        speaker_detection=False,
        speaker_count=None,
        device=Device.CPU,
        compute_type=ComputeType.INT8,
        timestamp="",
        temperature=0.0,
        initial_prompt=prompt,
        cpu_threads=4,
    )
    previous_threads = torch.get_num_threads()
    try:
        result = qwen3_transformers.transcribe(settings, model_dir / MODEL, audio)
    finally:
        torch.set_num_threads(previous_threads)
        gc.collect()
    assert settings.progress["current"] == settings.progress["total"]
    segments = result["segments"]
    assert segments
    previous_end = 0.0
    for segment in segments:
        start, end = segment["start"], segment["end"]
        assert math.isfinite(start) and math.isfinite(end)
        assert 0 <= start <= end <= seconds + 0.02
        assert start >= previous_end - 0.02
        assert segment["words"][0]["word"].strip() == segment["text"]
        previous_end = end
    return segments


def test_short_clip_is_transcribed_and_aligned(model_dir):
    segments = transcribe(model_dir, "sample_short.mp3", 3.2)
    text = "".join(segment["words"][0]["word"] for segment in segments)
    assert text.lower() == "this is a librivox recording."
    # Compare against the established Crisper/Whisper boundary baseline. The
    # separate aligner has an 80 ms grid and different boundary conventions.
    assert [s["start"] for s in segments] == pytest.approx([1.04, 1.50, 1.66, 1.80, 2.26], abs=0.30)
    assert [s["end"] for s in segments] == pytest.approx([1.50, 1.66, 1.80, 2.26, 3.20], abs=0.30)


def test_language_detection_and_context_prompt(model_dir):
    segments = transcribe(
        model_dir,
        "sample_short.mp3",
        3.2,
        language="auto-detect",
        prompt="LibriVox",
    )
    text = "".join(segment["words"][0]["word"] for segment in segments)
    assert text.lower() == "this is a librivox recording."


def test_long_form_preserves_text_and_original_word_times(model_dir):
    import jiwer

    segments = transcribe(model_dir, "wer_lagarde.mp3", 45)
    text = "".join(segment["words"][0]["word"] for segment in segments)
    reference = (FIXTURES / "reference.txt").read_text().split("pushing up inflation")[0]
    reference += "pushing up inflation"
    normalize = jiwer.Compose(
        [
            jiwer.ToLowerCase(),
            jiwer.SubstituteWords({"2%": "two percent"}),
            jiwer.RemovePunctuation(),
            jiwer.SubstituteRegexes({r"\s+": " "}),
            jiwer.Strip(),
            jiwer.ReduceToListOfListOfWords(),
        ]
    )
    wer = jiwer.wer(reference, text, reference_transform=normalize, hypothesis_transform=normalize)
    assert wer < 0.08, f"excerpt WER: {wer:.2%}; transcript: {text}"
    assert segments[-1]["end"] >= 43, "transcription stopped before the final chunk"
    # The last word occurs after multiple VAD chunks on the original timeline.
    inflation = segments[-1]
    assert 43 < inflation["start"] < 45


def test_native_language_tokenizers(model_dir):
    from aTrain_core.backends.qwen3_transformers import aligned_words
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(
        model_dir / "qwen3-forced-aligner-0.6b", local_files_only=True
    )
    for text, language in [
        ("ありがとう。", "Japanese"),
        ("２０２６年、ＡＩです。", "Japanese"),
        ("안녕하세요 세계!", "Korean"),
    ]:
        tokens = processor.split_words_for_alignment(text, language)
        assert tokens
        items = [{"text": token, "start_time": 0.0, "end_time": 0.1} for token in tokens]
        words = aligned_words(text, items, offset=0, duration=1)
        assert "".join(word["word"] for word in words) == text


def test_cli_runs_offline_in_child_and_writes_timestamped_outputs(model_dir):
    env = {
        **os.environ,
        "ATRAIN_USER_DIR": str(model_dir.parent),
        "HF_HUB_OFFLINE": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aTrain_core",
            "transcribe",
            str(FIXTURES / "sample_short.mp3"),
            "--model",
            MODEL,
            "--language",
            "en",
            "--device",
            "cpu",
            "--cpu-threads",
            "4",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    (output,) = (model_dir.parent / "transcriptions").glob("*")
    for filename in ["transcription.txt", "transcription.srt", "transcription.json"]:
        assert (output / filename).is_file()
    transcript = json.loads((output / "transcription.json").read_text())
    words = [word for segment in transcript["segments"] for word in segment["words"]]
    assert len(words) >= 5
    assert all(word["start"] <= word["end"] for word in words)
    assert "LibriVox" in (output / "transcription.txt").read_text()
    assert "seperate process" in (output / "log.txt").read_text()

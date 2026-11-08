"""Real CrisperWhisper inference, including the attention used for word timing.

Set ATRAIN_TEST_CRISPER=1 to download the pinned 3 GB model into a temporary
directory, or ATRAIN_CRISPER_MODEL_PATH to reuse a local model. CI runs this
separately because it needs substantially more memory than the tiny smoke test.
"""

import gc
import math
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("ATRAIN_TEST_CRISPER") == "1" or os.environ.get("ATRAIN_CRISPER_MODEL_PATH")
    ),
    reason="set ATRAIN_TEST_CRISPER=1 or ATRAIN_CRISPER_MODEL_PATH for real CrisperWhisper inference",
)


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    local = os.environ.get("ATRAIN_CRISPER_MODEL_PATH")
    if local:
        path = Path(local).resolve()
        assert (path / "model.safetensors").is_file(), f"Missing CrisperWhisper weights: {path}"
        return path

    from aTrain_core import load_resources

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(load_resources, "MODELS_DIR", tmp_path_factory.mktemp("crisper_models"))
        return load_resources.get_model("crisperwhisper-v2-large")


def transcribe(model_path, monkeypatch, clip, seconds):
    import torch
    from aTrain_core.backends import crisper_transformers
    from aTrain_core.settings import ComputeType, Device
    from faster_whisper.audio import decode_audio

    # Observe the real encoder output: this catches an ineffective patch even
    # when words and timestamps still look correct.
    encoder_calls = []
    suppress = crisper_transformers._suppress_encoder_attentions

    def observe_encoder(module, args, output):
        assert output.attentions is None, "unused encoder self-attention was retained"
        encoder_calls.append(True)

    def instrument(model):
        suppress(model)
        model._engine.model.get_encoder().register_forward_hook(observe_encoder)

    monkeypatch.setattr(crisper_transformers, "_suppress_encoder_attentions", instrument)
    audio = decode_audio(str(FIXTURES / clip))[: int(seconds * 16000)]
    previous_threads = torch.get_num_threads()
    try:
        model = crisper_transformers.load_model(model_path, Device.CPU, ComputeType.FLOAT32, 4)
        segments = crisper_transformers.transcribe_with_model(
            model,
            audio,
            language="en",
            initial_prompt=None,
            temperature=None,
            progress={},
            log=print,
        )["segments"]
    finally:
        torch.set_num_threads(previous_threads)
        gc.collect()

    assert encoder_calls
    assert segments
    previous_end = 0.0
    for segment in segments:
        start, end = segment["start"], segment["end"]
        assert math.isfinite(start) and math.isfinite(end)
        assert 0 <= start <= end <= seconds + 0.02
        assert start >= previous_end - 0.02
        previous_end = end
    return segments


def test_short_clip_matches_the_word_timestamp_baseline(model_path, monkeypatch):
    segments = transcribe(model_path, monkeypatch, "sample_short.mp3", 3.2)

    text = " ".join(segment["text"] for segment in segments)
    assert text.lower() == "this is a librivox recording."
    # Baseline from Transformers 4.57.3, allowing modest CPU/backend drift.
    assert [s["start"] for s in segments] == pytest.approx([1.04, 1.50, 1.66, 1.80, 2.26], abs=0.12)
    assert [s["end"] for s in segments] == pytest.approx([1.50, 1.66, 1.80, 2.26, 3.20], abs=0.12)


def test_long_form_excerpt_is_transcribed_to_the_end(model_path, monkeypatch):
    import jiwer

    segments = transcribe(model_path, monkeypatch, "wer_lagarde.mp3", 45)

    text = " ".join(segment["text"] for segment in segments)
    # The 45-second cut ends at this phrase in the existing human reference.
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
    assert wer < 0.05, f"CrisperWhisper excerpt WER: {wer:.2%}"
    assert segments[-1]["end"] >= 40, "long-form transcription stopped at the first chunk"

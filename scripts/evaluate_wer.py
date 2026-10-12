#!/usr/bin/env python3
"""Compare the word error rate (WER) of aTrain models on your own recording.

Maintainer tool for judging a model before it goes into a release, for
example a language-specific one. It transcribes the recording through aTrain
itself (`aTrain_core transcribe`) and scores the result against a reference
transcript, so the numbers match what users get.

    uv run scripts/evaluate_wer.py talk.mp3 talk.txt
    uv run scripts/evaluate_wer.py talk.mp3 talk.txt --models large-swedish large-v3-turbo --language sv
    uv run scripts/evaluate_wer.py talk.mp3 talk.txt --runs 3 --device gpu --max-wer 0.1

Models are downloaded once into a cache of their own (--cache-dir), separate
from the app's, so models you already use in aTrain are downloaded again.
Pass --language for non-English recordings: without it, English contraction
rules are applied when scoring.

Only models in models.json can be evaluated. For an unreleased model, add its
entry on a local branch: point it at its Hugging Face repo and run
scripts/refresh_model_hashes.py <key>, or, before uploading, put the folder in
<cache-dir>/models/<key> and list its file names under `files`.

The CI accuracy test (tests/core/test_wer_e2e.py) scores with the same
normalisation from this file.
"""

from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import jiwer
from aTrain_core.load_resources import load_model_config_file
from platformdirs import user_cache_path

DEFAULT_CACHE = user_cache_path("aTrain") / "wer-eval"


def wer_transform(english: bool = True) -> jiwer.Compose:
    """Normalise reference and transcript the same way before comparing.

    English contractions are expanded only for English: the rules would turn
    e.g. German "geht's" into "geht is" and inflate the error rate.
    """
    steps = [jiwer.ToLowerCase()]
    if english:
        steps.append(jiwer.ExpandCommonEnglishContractions())
    steps += [
        jiwer.SubstituteRegexes({r"-": " "}),  # "medium-term" -> "medium term"
        jiwer.RemovePunctuation(),
        jiwer.SubstituteRegexes({r"\s+": " "}),  # newlines and tabs too
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
    return jiwer.Compose(steps)


def transcript_text(output_dir: Path) -> str:
    """The transcript from an aTrain output folder, without its header lines."""
    lines = (output_dir / "transcription.txt").read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[2:])


def score(reference: str, hypothesis: str, english: bool = True) -> float:
    transform = wer_transform(english)
    return jiwer.wer(
        reference,
        hypothesis,
        reference_transform=transform,
        hypothesis_transform=transform,
    )


def check_models(models: list[str], language: str) -> list[str]:
    """Problems that would otherwise only show up after a model is downloaded."""
    config = load_model_config_file()
    problems = []
    for model in models:
        if model not in config:
            problems.append(f"{model} is not in models.json")
        elif (languages := config[model].get("languages")) and language not in languages:
            problems.append(
                f"{model} only supports {', '.join(languages)}; pass --language {languages[0]}"
            )
    return problems


def atrain_core(args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "ATRAIN_USER_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "aTrain_core", *args], env=env, capture_output=True, text=True
    )


def transcribe(audio: Path, model: str, language: str, device: str, data_dir: Path) -> str:
    """Transcribe a copy of `audio` and return the transcript text.

    aTrain renames input files that contain spaces, so the copy gets a fixed
    name. The copy and the output folder are removed afterwards, so the cache
    only keeps models.
    """
    clip = data_dir / f"wer-eval{audio.suffix}"
    shutil.copy(audio, clip)
    transcriptions = data_dir / "transcriptions"
    before = set(transcriptions.glob("*")) if transcriptions.exists() else set()
    try:
        result = atrain_core(
            ["transcribe", str(clip), "--model", model, "--device", device, "--language", language],
            data_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(f"transcription with {model} failed:\n{result.stderr}")
        new = [d for d in set(transcriptions.glob("*")) - before if d.is_dir()]
        if len(new) != 1:
            raise RuntimeError(f"expected one new output folder, found {len(new)}")
        text = transcript_text(new[0])
        shutil.rmtree(new[0])
        return text
    finally:
        clip.unlink(missing_ok=True)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("audio", type=Path, help="recording to transcribe")
    parser.add_argument("reference", type=Path, help="reference transcript, plain text")
    parser.add_argument(
        "--models", nargs="+", default=["large-v3-turbo"], help="model keys from models.json"
    )
    parser.add_argument(
        "--language", default="auto-detect", help="language code, default: auto-detect"
    )
    parser.add_argument(
        "--device", choices=["cpu", "gpu"], default="cpu", help="where to run, default: cpu"
    )
    parser.add_argument(
        "--runs", type=positive_int, default=1, help="runs per model, the median counts"
    )
    parser.add_argument(
        "--max-wer", type=float, help="exit with 1 if a model's median WER is above this, e.g. 0.1"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE,
        help=f"where models are kept between runs, default: {DEFAULT_CACHE}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    problems = [
        f"{path} does not exist" for path in (args.audio, args.reference) if not path.is_file()
    ]
    problems += check_models(args.models, args.language)
    if problems:
        raise SystemExit("\n".join(problems))
    # utf-8-sig: Notepad and PowerShell 5 save UTF-8 with a BOM, which would
    # otherwise count as part of the first word.
    reference = args.reference.read_text(encoding="utf-8-sig")
    english = args.language in ("en", "auto-detect")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"models cache: {args.cache_dir / 'models'}\n")

    rows = []
    for model in args.models:
        loaded = atrain_core(["load", model], args.cache_dir)
        if loaded.returncode != 0:
            raise SystemExit(f"could not load {model}:\n{loaded.stderr}")
        wers, seconds = [], []
        for _ in range(args.runs):
            start = time.monotonic()
            hypothesis = transcribe(args.audio, model, args.language, args.device, args.cache_dir)
            seconds.append(time.monotonic() - start)
            wers.append(score(reference, hypothesis, english))
        rows.append((model, wers, statistics.median(wers), statistics.median(seconds)))

    width = max(len("model"), *(len(model) for model, *_ in rows))
    print(f"{'model':<{width}}  {'median WER':>10}  {'runs':<24}  time")
    for model, wers, median, duration in rows:
        runs = ", ".join(f"{w:.2%}" for w in wers)
        print(f"{model:<{width}}  {median:>10.2%}  {runs:<24}  {duration:.0f} s")

    if args.max_wer is not None:
        failed = [model for model, _, median, _ in rows if median > args.max_wer]
        if failed:
            print(f"\nabove {args.max_wer:.0%}: {', '.join(failed)}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

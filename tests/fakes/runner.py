"""Fake model factories for spawned runner children (a spawned child can't see
monkeypatches). Configured through the FAKE_RUNNER environment variable, a JSON object:
{"crash_on_job": 2}, {"sleep": 30}."""

import json
import os
import time

from aTrain_core.backends.common import words_to_segments


def _config() -> dict:
    return json.loads(os.environ.get("FAKE_RUNNER", "{}"))


class FakeTranscriber:
    backend = "faster-whisper"

    def __init__(self):
        self.jobs = 0

    def transcribe(self, audio, *, language, initial_prompt, temperature, progress, log):
        self.jobs += 1
        config = _config()
        if self.jobs == config.get("crash_on_job"):
            os._exit(1)
        progress["task"] = "Transcribe"
        time.sleep(config.get("sleep", 0))
        progress["current"], progress["total"] = 1, 1
        return {"segments": words_to_segments([{"word": " Hello.", "start": 0.0, "end": 0.5}])}


def load_transcriber(key, model_path=None):
    return FakeTranscriber()

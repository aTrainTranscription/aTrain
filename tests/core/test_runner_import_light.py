"""A spawned phase child imports aTrain_core.runner first; that import must not pull in
the GUI stack or the model libraries (they are imported when a model is loaded)."""

import subprocess
import sys

HEAVY = [
    "nicegui",
    "webview",
    "fastapi",
    "torch",
    "faster_whisper",
    "pyannote.audio",
    "crisperwhisper",
]


def test_runner_import_is_light():
    code = f"import sys, aTrain_core.runner; print([m for m in {HEAVY!r} if m in sys.modules])"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"

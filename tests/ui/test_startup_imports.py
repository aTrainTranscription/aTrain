"""Guard the lazy-loading of torch at startup.

The splash screen only shows while torch is still unloaded
(`splash_screen()` checks `"torch" not in sys.modules`), and
`utils/transcription.py` defers its aTrain_core import for the same reason.
Both are defeated the moment any page module pulls torch in at import time -
which is easy to do by accident, because half of aTrain_core reaches it
through faster_whisper.

This has to run in a subprocess. In the pytest process some other test has
long imported torch, so an in-process assertion would pass no matter what.
"""

import json
import subprocess
import sys

import pytest

# The modules that make up the transcribe page, i.e. what is imported before
# the first window can appear. The splash itself is excluded: it is the thing
# that loads torch on purpose.
STARTUP_MODULES = [
    "aTrain.components.settings.advanced",
    "aTrain.components.settings.file",
    "aTrain.components.settings.model",
    "aTrain.components.settings.language",
    "aTrain.components.settings.speaker_detection",
    "aTrain.components.settings.speaker_count",
]

PROBE = """
import importlib, json, sys
for name in {modules!r}:
    importlib.import_module(name)
print(json.dumps({{"torch": "torch" in sys.modules}}))
"""


@pytest.mark.parametrize("module", STARTUP_MODULES)
def test_startup_module_does_not_import_torch(module):
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(modules=[module])],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert json.loads(result.stdout)["torch"] is False, (
        f"{module} pulls torch in at import time, which defeats the splash screen "
        "and the deferred imports on the startup path"
    )

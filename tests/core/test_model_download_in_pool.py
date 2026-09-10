"""Regression test for the huggingface `http_get` patch in `download_model`.

Mirrors the app's sequence: the Models page downloads a model in a pool worker
with a progress proxy from a `multiprocessing.Manager`, the manager goes away
with the dialog, and a later transcription downloads another model in the same
worker without a progress proxy. Before the fix the worker kept the patched
`http_get` and wrote to the dead proxy (FileNotFoundError, Windows and Linux
alike). One worker makes the reuse deterministic; in the app it depends on
which worker picks up the task, which is why this was intermittent.

Network: downloads tiny (78 MB) and speaker-detection (34 MB) into a fresh
data dir.
"""

import os
import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent(
    """
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import Manager

    from aTrain_core.load_resources import get_model

    if __name__ == "__main__":
        with ProcessPoolExecutor(max_workers=1) as pool:
            with Manager() as manager:
                progress = manager.dict({"current": 0, "total": 999999})
                pool.submit(get_model, "tiny", progress=progress).result()
                assert progress["current"] > 0, "progress never reported"
            # The manager is gone; the worker must not try to reach it again.
            pool.submit(get_model, "speaker-detection").result()
        print("second download ok")
    """
)


def test_second_download_after_a_progress_download_in_the_same_worker(tmp_path):
    script = tmp_path / "sequence.py"
    script.write_text(SCRIPT)
    env = {**os.environ, "ATRAIN_USER_DIR": str(tmp_path / "data")}

    result = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=900
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "second download ok" in result.stdout
    assert any(tmp_path.rglob("speaker-detection")), "model did not land in the test data dir"

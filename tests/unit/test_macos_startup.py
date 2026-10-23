"""The PR CI startup checks require a completed main page, without launching an app here."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="macOS startup steps use Bash and POSIX process management",
)
@pytest.mark.parametrize("job", ["macos-app-start", "macos27-app-start"])
@pytest.mark.parametrize(
    ("log", "early_exit", "success"),
    [
        ("Running aTrain\n", False, False),
        ("Running aTrain\nTraceback (most recent call last):\nImportError: scipy\n", False, False),
        ("Running aTrain\naTrain startup failed\n", False, False),
        ("Running aTrain\naTrain startup ready\naTrain startup failed\n", False, False),
        ("Running aTrain\naTrain startup ready\n", False, True),
        ("Running aTrain\naTrain startup ready\n", True, False),
    ],
    ids=["no-readiness", "import-error", "init-failure", "failure-after-ready", "ready", "exit"],
)
def test_native_startup_requires_completed_initialization(tmp_path, job, log, early_exit, success):
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    step = next(
        step for step in workflow["jobs"][job]["steps"] if "script -q" in step.get("run", "")
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "script": (
            '#!/bin/sh\nprintf "%s" "$SMOKE_LOG" > "$2"\n'
            '[ "$EARLY_EXIT" = false ] || exit 0\nexec /bin/sleep 10\n'
        ),
        "sleep": "#!/bin/sh\nexec /bin/sleep 0.2\n",
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
            "SMOKE_LOG": log,
            "EARLY_EXIT": str(early_exit).lower(),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    if not success:
        assert "::error::" in result.stdout

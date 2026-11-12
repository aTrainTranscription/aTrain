"""Keep ad-hoc macOS builds as test artifacts, never published installers."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL_TEST = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="The release guard runs in Bash on Ubuntu; these stubs need POSIX paths",
)


@pytest.fixture(scope="module")
def jobs():
    workflow = REPO_ROOT / ".github" / "workflows" / "release.yml"
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]


def signing_step(jobs):
    return next(step for step in jobs["build-macos-dmg"]["steps"] if step.get("id") == "sign-dmg")


def publishing_guard(jobs):
    return jobs["publish-macos-to-zenodo"]["steps"][0]


def test_verified_signing_output_reaches_the_first_publishing_step(jobs):
    build = jobs["build-macos-dmg"]
    sign = signing_step(jobs)
    guard = publishing_guard(jobs)

    assert sign["if"] == "env.MACOS_SIGN == 'true'"
    assert build["outputs"]["signing-verified"] == (
        "${{ steps." + sign["id"] + ".outputs.verified }}"
    )
    assert guard["env"]["MACOS_SIGNING_VERIFIED"] == (
        "${{ needs.build-macos-dmg.outputs.signing-verified }}"
    )
    assert guard["shell"] == "bash"
    assert "if" not in guard
    assert not guard.get("continue-on-error", False)
    assert not sign.get("continue-on-error", False)
    assert not jobs["publish-macos-to-zenodo"].get("continue-on-error", False)
    assert "signing-verified" not in jobs["publish-macos-to-zenodo"]["if"]


def test_unsigned_builds_still_upload_workflow_artifacts(jobs):
    upload = next(
        step
        for step in jobs["build-macos-dmg"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
        and "aTrain-*.dmg" in step["with"]["path"]
    )
    assert "if" not in upload


@SHELL_TEST
@pytest.mark.parametrize("verified", [None, "", "false", "TRUE", "1", "true\n"])
def test_publishing_guard_refuses_unverified_builds(jobs, tmp_path, verified):
    env = {key: value for key, value in os.environ.items() if key != "MACOS_SIGNING_VERIFIED"}
    # A missing Zenodo token must not bypass the guard: GitHub uploads also
    # publish integrity files before the optional Zenodo upload.
    env["ZENODO_TOKEN"] = ""
    if verified is not None:
        env["MACOS_SIGNING_VERIFIED"] = verified

    result = subprocess.run(
        ["bash", "-c", publishing_guard(jobs)["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "::error::" in result.stdout


@SHELL_TEST
def test_publishing_guard_accepts_verified_builds(jobs, tmp_path):
    result = subprocess.run(
        ["bash", "-c", publishing_guard(jobs)["run"]],
        cwd=tmp_path,
        env={**os.environ, "MACOS_SIGNING_VERIFIED": "true"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@SHELL_TEST
@pytest.mark.parametrize("failure", [None, "sign", "notarize", "verify", "gatekeeper"])
def test_dmg_output_requires_every_signing_and_verification_command(jobs, tmp_path, failure):
    """Run the real step body with local command stubs, never Apple services."""
    command_log = tmp_path / "commands.log"
    output = tmp_path / "github-output"
    output.touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    notarize = tmp_path / ".github" / "scripts" / "macos-notarize.sh"
    notarize.parent.mkdir(parents=True)
    stubs = {
        bin_dir / "codesign": ('step=sign\n[ "$1" != --verify ] || step=verify\n'),
        notarize: "step=notarize\n",
        bin_dir / "spctl": "step=gatekeeper\n",
    }
    for path, body in stubs.items():
        path.write_text(
            "#!/bin/sh\n"
            + body
            + 'printf "%s\\n" "$step" >> "$COMMAND_LOG"\n'
            + '[ "$FAIL_COMMAND" != "$step" ]\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
    # The signing retry should exercise the failure path without waiting.
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    script = signing_step(jobs)["run"].replace("${{ steps.version.outputs.version }}", "0.0.0-test")

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "MACOS_SIGNING_IDENTITY": "Dummy Developer ID",
            "GITHUB_OUTPUT": str(output),
            "COMMAND_LOG": str(command_log),
            "FAIL_COMMAND": failure or "",
        },
        capture_output=True,
        text=True,
    )

    if failure is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert command_log.read_text().splitlines() == [
            "sign",
            "notarize",
            "verify",
            "gatekeeper",
        ]
        assert output.read_text().splitlines() == ["verified=true"]
    else:
        assert result.returncode != 0
        assert "verified=true" not in output.read_text()

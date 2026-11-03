"""Exercise the release uploader against a local curl stub, never Zenodo."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "zenodo-upload.sh"
BASE = "https://zenodo.invalid"
VERSION = "1.5.0"
WINDOWS_FILE = "aTrain-1.5.0.msix"
MACOS_FILE = "aTrain-1.5.0-macos-arm64.dmg"


def draft(*filenames, version=VERSION, submitted=False):
    return {
        "id": 123,
        "submitted": submitted,
        "metadata": {"version": version},
        "links": {"bucket": f"{BASE}/api/files/bucket"},
        "files": [
            {"id": f"file-{index}", "filename": filename}
            for index, filename in enumerate(filenames)
        ],
    }


def exchange(method, path, response=None, returncode=0):
    return {"method": method, "path": path, "response": response, "returncode": returncode}


@pytest.fixture
def upload(tmp_path):
    # Git Bash on Windows cannot directly execute this Python shebang stub.
    # The workflow wiring test below remains part of every platform's checks.
    if os.name == "nt" or not shutil.which("bash") or not shutil.which("jq"):
        pytest.skip("the shell integration tests require POSIX, bash and jq")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
url = args[-1]
call = {"method": method, "path": url.removeprefix(os.environ["ZENODO_BASE"] + "/api")}
if "--upload-file" in args:
    call["upload"] = Path(args[args.index("--upload-file") + 1]).name
if "-d" in args:
    data = args[args.index("-d") + 1]
    call["data"] = json.loads(Path(data[1:]).read_text() if data.startswith("@") else data)
with open(os.environ["MOCK_CALLS"], "a") as stream:
    stream.write(json.dumps(call) + "\n")
queue = Path(os.environ["MOCK_RESPONSES"])
responses = json.loads(queue.read_text())
if not responses:
    sys.exit("unexpected curl call: " + repr(call))
expected = responses.pop(0)
queue.write_text(json.dumps(responses))
assert (method, call["path"]) == (expected["method"], expected["path"]), (call, expected)
if expected["returncode"]:
    sys.exit(expected["returncode"])
if "-o" not in args:
    print(json.dumps(expected["response"]))
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"title": "aTrain", "related_identifiers": []}))

    def run(responses, *filenames, **variables):
        queue = tmp_path / "responses.json"
        calls = tmp_path / "calls.jsonl"
        output = tmp_path / "github-output"
        queue.write_text(json.dumps(responses))
        calls.write_text("")
        output.write_text("")
        for filename in filenames:
            (tmp_path / filename).write_text("release artifact")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ZENODO_") and key != "GITHUB_OUTPUT"
        }
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
            ZENODO_TOKEN="test-token",  # noqa: S106 - only the local curl stub sees this
            ZENODO_BASE=BASE,
            ZENODO_METADATA=str(metadata),
            GITHUB_REPOSITORY="owner/aTrain",
            GITHUB_OUTPUT=str(output),
            MOCK_CALLS=str(calls),
            MOCK_RESPONSES=str(queue),
        )
        env.update(variables)
        result = subprocess.run(
            ["bash", str(SCRIPT), VERSION, *filenames],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            assert json.loads(queue.read_text()) == [], "expected API calls were skipped"
        return (
            result,
            [json.loads(line) for line in calls.read_text().splitlines()],
            output.read_text(),
        )

    return run


def test_first_concept_draft_is_handed_to_macos_without_a_concept_id(upload):
    result, _, output = upload(
        [
            exchange("POST", "/deposit/depositions", draft()),
            exchange("PUT", f"/files/bucket/{WINDOWS_FILE}"),
            exchange("PUT", "/deposit/depositions/123"),
        ],
        WINDOWS_FILE,
    )
    assert result.returncode == 0, result.stderr
    assert output == "draft-id=123\n"
    assert "First record" in result.stdout

    result, calls, output = upload(
        [
            exchange("GET", "/deposit/depositions/123", draft(WINDOWS_FILE, "checksums.txt")),
            exchange("PUT", f"/files/bucket/{MACOS_FILE}"),
            exchange("PUT", "/deposit/depositions/123"),
        ],
        MACOS_FILE,
        ZENODO_APPEND="1",
        ZENODO_DRAFT_ID=output.strip().split("=", 1)[1],
    )
    assert result.returncode == 0, result.stderr
    assert [call["method"] for call in calls] == ["GET", "PUT", "PUT"]
    assert output == "draft-id=123\n"
    assert calls[-1]["data"]["metadata"]["version"] == VERSION
    assert "First record" not in result.stdout


def test_append_retry_only_replaces_its_own_files(upload):
    result, calls, output = upload(
        [
            exchange("GET", "/deposit/depositions/123", draft(WINDOWS_FILE, MACOS_FILE)),
            exchange("DELETE", "/deposit/depositions/123/files/file-1"),
            exchange("PUT", f"/files/bucket/{MACOS_FILE}"),
            exchange("PUT", "/deposit/depositions/123"),
        ],
        MACOS_FILE,
        ZENODO_APPEND="1",
        ZENODO_DRAFT_ID="123",
        ZENODO_CONCEPT_ID="456",  # The handed-off draft takes precedence.
    )
    assert result.returncode == 0, result.stderr
    assert calls[1]["path"].endswith("/file-1")
    assert output == "draft-id=123\n"


@pytest.mark.parametrize(
    "deposition",
    [draft(version="1.4.0"), draft(submitted=True), draft(submitted=None)],
    ids=["different-version", "submitted", "missing-submitted-state"],
)
def test_append_rejects_another_version_or_published_record_before_mutation(upload, deposition):
    result, calls, output = upload(
        [exchange("GET", "/deposit/depositions/123", deposition)],
        MACOS_FILE,
        ZENODO_APPEND="1",
        ZENODO_DRAFT_ID="123",
    )
    assert result.returncode != 0
    assert "unpublished Zenodo draft" in result.stdout + result.stderr
    assert [call["method"] for call in calls] == ["GET"]
    assert output == ""


@pytest.mark.parametrize("failure", ["upload", "metadata"])
def test_draft_output_is_not_emitted_when_an_upload_fails(upload, failure):
    responses = [exchange("POST", "/deposit/depositions", draft())]
    responses.append(
        exchange(
            "PUT", f"/files/bucket/{WINDOWS_FILE}", returncode=22 if failure == "upload" else 0
        )
    )
    if failure == "metadata":
        responses.append(exchange("PUT", "/deposit/depositions/123", returncode=22))
    result, _, output = upload(responses, WINDOWS_FILE)
    assert result.returncode != 0
    assert output == ""


def test_append_can_still_find_the_draft_by_concept_id(upload):
    result, _, output = upload(
        [
            exchange("GET", "/deposit/depositions?q=conceptrecid:456&status=draft", [draft()]),
            exchange("GET", "/deposit/depositions/123", draft(WINDOWS_FILE)),
            exchange("PUT", f"/files/bucket/{MACOS_FILE}"),
            exchange("PUT", "/deposit/depositions/123"),
        ],
        MACOS_FILE,
        ZENODO_APPEND="1",
        ZENODO_CONCEPT_ID="456",
    )
    assert result.returncode == 0, result.stderr
    assert output == "draft-id=123\n"


def test_local_upload_does_not_require_github_output(upload):
    result, _, output = upload(
        [
            exchange("POST", "/deposit/depositions", draft()),
            exchange("PUT", f"/files/bucket/{WINDOWS_FILE}"),
            exchange("PUT", "/deposit/depositions/123"),
        ],
        WINDOWS_FILE,
        GITHUB_OUTPUT="",
    )
    assert result.returncode == 0, result.stderr
    assert output == ""


def test_release_workflow_passes_the_windows_draft_to_the_macos_upload():
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text())
    windows = workflow["jobs"]["publish-to-zenodo"]
    uploader = next(
        step
        for step in windows["steps"]
        if ".github/scripts/zenodo-upload.sh" in step.get("run", "")
    )
    assert windows["outputs"]["draft-id"] == "${{ steps." + uploader["id"] + ".outputs.draft-id }}"
    macos = workflow["jobs"]["publish-macos-to-zenodo"]
    assert "publish-to-zenodo" in macos["needs"]
    append = next(
        step for step in macos["steps"] if step.get("env", {}).get("ZENODO_APPEND") == "1"
    )
    assert append["env"]["ZENODO_DRAFT_ID"] == "${{ needs.publish-to-zenodo.outputs.draft-id }}"

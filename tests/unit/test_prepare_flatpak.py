from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / ".github/scripts/prepare-flatpak.py"
TEMPLATE = ROOT / "packaging/flatpak/io.github.juergenfleiss.aTrain.yml"
SPEC = importlib.util.spec_from_file_location("prepare_flatpak", SCRIPT)
prepare_flatpak = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(prepare_flatpak)

COMMIT = "a" * 40
LOCK = (
    "[[packages]]\nname = 'example'\nversion = '1'\n"
    f"wheels = [{{ url = 'https://example.invalid/example-1-py3-none-any.whl', "
    f"hashes = {{ sha256 = '{'a' * 64}' }} }}]\n"
)


def artifact(filename: str, digest: str = "a" * 64) -> dict:
    return {"url": f"https://example.invalid/{filename}", "hashes": {"sha256": digest}}


def platform(arch: str):
    return prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags(arch)],
    )


def wheel_package(*wheels: dict, name: str = "example", version: str = "1") -> dict:
    return {"name": name, "version": version, "wheels": list(wheels)}


@pytest.fixture
def pinned_version(monkeypatch) -> str:
    """Decouple CLI tests from the project's current release metadata."""
    monkeypatch.setattr(prepare_flatpak, "source_version", lambda root: "1.2.3")
    monkeypatch.setattr(prepare_flatpak, "metainfo_version", lambda root: "1.2.3")
    return "1.2.3"


def cli_args(tmp_path: Path, *extra: str) -> list[str]:
    lock = tmp_path / "pylock.toml"
    lock.write_text(LOCK)
    template = tmp_path / "manifest.yml"
    template.write_text("modules:\n  - name: atrain\n    sources: []\n")
    return [
        "--lock", str(lock),
        "--template", str(template),
        "--output-dir", str(tmp_path / "out"),
        "--commit", COMMIT,
        *extra,
    ]  # fmt: skip


def generated_source(tmp_path: Path) -> list[dict]:
    manifest = prepare_flatpak.yaml.safe_load((tmp_path / "out/manifest.yml").read_text())
    return manifest["modules"][-1]["sources"]


# --- lock parsing -----------------------------------------------------------


def test_pylock_applies_linux_markers_per_architecture(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        "[[packages]]\nname = 'common'\nversion = '1'\n"
        "[[packages]]\nname = 'x86'\nversion = '1'\nmarker = \"platform_machine == 'x86_64'\"\n"
        "[[packages]]\nname = 'arm'\nversion = '1'\nmarker = \"platform_machine == 'aarch64'\"\n"
        "[[packages]]\nname = 'win'\nversion = '1'\nmarker = \"sys_platform == 'win32'\"\n"
    )
    assert set(prepare_flatpak.lock_packages(lock, "x86_64")) == {("common", "1"), ("x86", "1")}
    assert set(prepare_flatpak.lock_packages(lock, "aarch64")) == {("arm", "1"), ("common", "1")}


def test_pylock_rejects_duplicate_entries(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.toml"
    # Names are compared after PEP 503 normalization.
    lock.write_text(
        "[[packages]]\nname = 'Foo_Bar'\nversion = '1'\n"
        "[[packages]]\nname = 'foo-bar'\nversion = '1'\n"
    )
    with pytest.raises(ValueError, match="ambiguous"):
        prepare_flatpak.lock_packages(lock, "x86_64")


# --- wheel selection --------------------------------------------------------


def test_selection_prefers_cp313_over_abi3_and_ignores_free_threaded() -> None:
    package = wheel_package(
        artifact("example-1-cp313-abi3-manylinux_2_17_x86_64.whl", "b" * 64),
        artifact("example-1-cp313-cp313-manylinux_2_17_x86_64.whl", "c" * 64),
        artifact("example-1-cp313-cp313t-manylinux_2_42_x86_64.whl", "d" * 64),
    )
    assert prepare_flatpak.choose_download(package, platform("x86_64")).sha256 == "c" * 64


def test_gnome_50_glibc_wheels_are_accepted() -> None:
    # req2flatpak's own Linux targets stop at glibc 2.35.
    package = wheel_package(artifact("example-1-cp313-cp313-manylinux_2_42_x86_64.whl"))
    assert prepare_flatpak.choose_download(package, platform("x86_64")).filename.endswith(
        "manylinux_2_42_x86_64.whl"
    )


def test_selection_among_identical_filenames_is_deterministic() -> None:
    package = wheel_package(
        {
            "url": "https://example.invalid/z/example-1-cp313-cp313-manylinux_2_17_x86_64.whl",
            "hashes": {"sha256": "b" * 64},
        },
        {
            "url": "https://example.invalid/a/example-1-cp313-cp313-manylinux_2_17_x86_64.whl",
            "hashes": {"sha256": "a" * 64},
        },
    )
    assert prepare_flatpak.choose_download(package, platform("x86_64")).sha256 == "a" * 64


@pytest.mark.parametrize(
    "filename",
    [
        "example-1-cp314-cp314-manylinux_2_17_aarch64.whl",
        "example-1-cp313-cp313-musllinux_1_2_aarch64.whl",
        "example-1-cp313-cp313-manylinux_2_17_x86_64.whl",
    ],
)
def test_incompatible_wheels_are_rejected(filename: str) -> None:
    with pytest.raises(ValueError, match="no supported"):
        prepare_flatpak.choose_download(wheel_package(artifact(filename)), platform("aarch64"))


def test_sdists_are_allowed_only_for_the_allowlist() -> None:
    allowed = next(iter(prepare_flatpak.ALLOWED_SDISTS))
    package = {"name": allowed, "version": "1", "sdist": artifact(f"{allowed}-1.tar.gz")}
    assert prepare_flatpak.choose_download(package, platform("aarch64")).url.endswith(".tar.gz")

    other = {"name": "not-allowlisted", "version": "1", "sdist": artifact("x-1.tar.gz")}
    with pytest.raises(ValueError, match="no supported"):
        prepare_flatpak.choose_download(other, platform("aarch64"))


# --- artifact validation ----------------------------------------------------


@pytest.mark.parametrize(
    ("wheel", "error"),
    [
        (artifact("example-1-py3-none-any.whl", "bad"), "invalid artifact hash"),
        ({"url": "https://example.invalid/example-1-py3-none-any.whl"}, "invalid artifact hash"),
        (
            {
                "url": "http://example.invalid/example-1-py3-none-any.whl",
                "hashes": {"sha256": "a" * 64},
            },
            "unsupported artifact URL",
        ),
        (artifact("not-a-wheel.whl"), "invalid wheel filename"),
    ],
)
def test_invalid_artifacts_are_rejected(wheel: dict, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        prepare_flatpak.choose_download(wheel_package(wheel), platform("x86_64"))


# --- module generation ------------------------------------------------------


def test_module_is_arch_restricted_and_installs_offline() -> None:
    module = prepare_flatpak.python_module(
        "x86_64",
        {
            ("example", "1"): wheel_package(
                artifact("example-1-cp313-cp313-manylinux_2_28_x86_64.whl")
            )
        },
    )
    assert module["name"] == "python-dependencies-x86-64"
    assert module["only-arches"] == ["x86_64"]
    assert "--no-index" in module["build-commands"][0]
    assert module["build-commands"][0].endswith(" example")
    assert [source["url"] for source in module["sources"]] == [
        "https://example.invalid/example-1-cp313-cp313-manylinux_2_28_x86_64.whl"
    ]
    assert "dest-filename" not in module["sources"][0]


def test_url_escaped_wheel_is_staged_under_its_real_filename() -> None:
    # PyTorch index URLs escape the local version separator (+ -> %2B).
    module = prepare_flatpak.python_module(
        "aarch64",
        {
            ("example", "1+cu128"): wheel_package(
                artifact("example-1%2Bcu128-cp313-cp313-manylinux_2_28_aarch64.whl"),
                version="1+cu128",
            )
        },
    )
    [source] = module["sources"]
    assert source["url"].endswith("example-1%2Bcu128-cp313-cp313-manylinux_2_28_aarch64.whl")
    assert source["dest-filename"] == "example-1+cu128-cp313-cp313-manylinux_2_28_aarch64.whl"


# --- CLI --------------------------------------------------------------------


def test_cli_pins_git_source_and_is_idempotent(tmp_path: Path, pinned_version, capsys) -> None:
    args = cli_args(tmp_path, "--tag", f"v{pinned_version}")
    assert prepare_flatpak.main(args) == 0
    assert capsys.readouterr().out.splitlines() == [f"version={pinned_version}", "stable=true"]

    out = tmp_path / "out"
    assert {path.name for path in out.iterdir()} == {
        "atrain_python_dependencies.json",
        "flathub.json",
        "manifest.yml",
    }
    data = json.loads((out / "atrain_python_dependencies.json").read_text())
    assert [module["only-arches"] for module in data["modules"]] == [["x86_64"], ["aarch64"]]
    assert json.loads((out / "flathub.json").read_text()) == {"only-arches": ["x86_64", "aarch64"]}
    assert generated_source(tmp_path) == [
        {
            "type": "git",
            "url": "https://github.com/aTrainTranscription/aTrain.git",
            "commit": COMMIT,
            "tag": f"v{pinned_version}",
        }
    ]

    original = {path.name: path.read_bytes() for path in out.iterdir()}
    assert prepare_flatpak.main(args) == 0
    assert {path.name: path.read_bytes() for path in out.iterdir()} == original


def test_cli_local_source_replaces_git_source(tmp_path: Path, pinned_version) -> None:
    assert prepare_flatpak.main(cli_args(tmp_path, "--local-source", str(tmp_path))) == 0
    assert generated_source(tmp_path) == [
        {"type": "dir", "path": str(tmp_path.resolve()), "skip": prepare_flatpak.LOCAL_SOURCE_SKIPS}
    ]


def test_cli_reports_prereleases_as_unstable(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(prepare_flatpak, "source_version", lambda root: "2.0.0rc1")
    monkeypatch.setattr(prepare_flatpak, "metainfo_version", lambda root: "2.0.0rc1")
    assert prepare_flatpak.main(cli_args(tmp_path, "--tag", "v2.0.0rc1")) == 0
    assert "stable=false" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize(
    "extra",
    [
        ["--commit", "invalid"],
        ["--tag", "v0.0.0"],  # does not match version.py
        ["--tag", "not-a-version"],
        ["--local-source", "/does/not/exist"],
    ],
)
def test_cli_rejects_invalid_arguments(tmp_path: Path, pinned_version, extra: list[str]) -> None:
    with pytest.raises(SystemExit):
        prepare_flatpak.main(cli_args(tmp_path, *extra))


def test_cli_rejects_appstream_version_mismatch(
    tmp_path: Path, pinned_version, monkeypatch
) -> None:
    monkeypatch.setattr(prepare_flatpak, "metainfo_version", lambda root: "0.0.0")
    with pytest.raises(SystemExit):
        prepare_flatpak.main(cli_args(tmp_path, "--tag", f"v{pinned_version}"))


def test_real_template_and_project_metadata(tmp_path: Path) -> None:
    """Uses the tracked template, version.py and AppStream metadata unpatched."""
    args = cli_args(tmp_path, "--template", str(TEMPLATE))
    assert prepare_flatpak.main(args) == 0
    manifest = prepare_flatpak.yaml.safe_load((tmp_path / "out" / TEMPLATE.name).read_text())
    assert "atrain_python_dependencies.json" in manifest["modules"]
    assert manifest["modules"][-1]["sources"][0]["commit"] == COMMIT

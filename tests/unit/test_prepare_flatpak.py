from __future__ import annotations

import importlib.util
import json
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github/scripts/prepare-flatpak.py"
VERSION = runpy.run_path(str(SCRIPT.parents[2] / "aTrain/version.py"))["__version__"]
SPEC = importlib.util.spec_from_file_location("prepare_flatpak", SCRIPT)
prepare_flatpak = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(prepare_flatpak)


def artifact(filename: str, digest: str = "a" * 64) -> dict[str, str]:
    return {"url": f"https://example.invalid/{filename}", "hashes": {"sha256": digest}}


def test_pylock_applies_linux_markers_per_architecture(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        "[[packages]]\nname = 'common'\nversion = '1'\nwheels = []\n"
        "[[packages]]\nname = 'x86'\nversion = '1'\nmarker = \"platform_machine == 'x86_64'\"\nwheels = []\n"
        "[[packages]]\nname = 'arm'\nversion = '1'\nmarker = \"platform_machine == 'aarch64'\"\nwheels = []\n"
    )
    assert set(prepare_flatpak.lock_packages(lock, "x86_64")) == {("common", "1"), ("x86", "1")}
    assert set(prepare_flatpak.lock_packages(lock, "aarch64")) == {("arm", "1"), ("common", "1")}


def test_req2flatpak_selection_prefers_cp313_then_abi3() -> None:
    package = {
        "name": "example",
        "version": "1",
        "wheels": [
            artifact("example-1-cp313-abi3-manylinux_2_17_x86_64.whl", "b" * 64),
            artifact("example-1-cp313-cp313-manylinux_2_17_x86_64.whl", "c" * 64),
            artifact("example-1-cp313-cp313t-manylinux_2_42_x86_64.whl", "d" * 64),
        ],
    }

    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("x86_64")],
    )
    assert prepare_flatpak.choose_download(package, platform).sha256 == "c" * 64


def test_source_artifacts_are_strictly_allowlisted() -> None:
    package = {
        "name": "proxy-tools",
        "version": "1",
        "sdist": artifact("proxy-tools-1.tar.gz"),
    }
    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("aarch64")],
    )
    assert prepare_flatpak.choose_download(package, platform).url.endswith(".tar.gz")
    with pytest.raises(ValueError, match="no supported"):
        prepare_flatpak.choose_download(
            {"name": "scipy", "version": "1", "sdist": artifact("scipy-1.tar.gz")},
            platform,
        )


def test_x86_module_generates_locked_torchcodec_normally() -> None:
    packages = {
        ("torchcodec", "0.10.0"): {
            "name": "torchcodec",
            "version": "0.10.0",
            "wheels": [artifact("torchcodec-0.10.0-cp313-cp313-manylinux_2_28_x86_64.whl")],
        }
    }
    module = prepare_flatpak.python_module("x86_64", packages)
    assert len(module["sources"]) == 1
    assert module["build-commands"][0].endswith(" torchcodec")
    assert "torchcodec-0.10.0-" in module["sources"][0]["url"]


def test_arm_module_generates_locked_torchcodec_normally() -> None:
    packages = {
        ("torchcodec", "0.10.0+cu128"): {
            "name": "torchcodec",
            "version": "0.10.0+cu128",
            "wheels": [artifact("torchcodec-0.10.0+cu128-cp313-cp313-manylinux_2_28_aarch64.whl")],
        }
    }
    module = prepare_flatpak.python_module("aarch64", packages)
    assert len(module["sources"]) == 1
    assert module["build-commands"][0].endswith(" torchcodec")
    assert "torchcodec-0.10.0+cu128-" in module["sources"][0]["url"]


def test_cli_validates_source_pin_tag_and_uses_tracked_metadata(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.flatpak.toml"
    lock.write_text(
        "[[packages]]\nname = 'example'\nversion = '1'\nwheels = [{ url = 'https://example.invalid/example-1-py3-none-any.whl', hashes = { sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' } }]\n"
        "[[packages]]\nname = 'torch'\nversion = '2.9.1'\nwheels = [{ url = 'https://example.invalid/torch-2.9.1-py3-none-any.whl', hashes = { sha256 = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' } }]\n"
    )
    template = tmp_path / "manifest.yml"
    template.write_text("modules:\n  - name: atrain\n    sources: []\n")
    output = tmp_path / "out"
    args = [
        "--lock",
        str(lock),
        "--template",
        str(template),
        "--output-dir",
        str(output),
        "--commit",
        "a" * 40,
        "--tag",
        f"v{VERSION}",
    ]
    assert prepare_flatpak.main(args) == 0
    data = json.loads((output / "atrain_python_dependencies.json").read_text())
    assert data["name"] and data["buildsystem"] == "simple"
    assert data["build-commands"]
    assert [module["only-arches"] for module in data["modules"]] == [["x86_64"], ["aarch64"]]
    assert not (output / "io.github.juergenfleiss.aTrain.metainfo.xml").exists()
    manifest = prepare_flatpak.yaml.safe_load(
        (output / "manifest.yml").read_text()
    )
    assert manifest["modules"][-1]["sources"] == [
        {
            "type": "git",
            "url": "https://github.com/aTrainTranscription/aTrain.git",
            "commit": "a" * 40,
            "tag": f"v{VERSION}",
        }
    ]
    original = {path.name: path.read_bytes() for path in output.iterdir()}
    assert prepare_flatpak.main(args) == 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original
    with pytest.raises(SystemExit):
        prepare_flatpak.main([*args, "--commit", "invalid"])
    with pytest.raises(SystemExit):
        prepare_flatpak.main([*args, "--tag", "v0.0.0"])
    with pytest.raises(SystemExit):
        prepare_flatpak.main([*args, "--tag", "not-a-version"])


def test_cli_rejects_appstream_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "pylock.flatpak.toml"
    lock.write_text("packages = []\n")
    template = tmp_path / "manifest.yml"
    template.write_text("modules:\n  - name: atrain\n    sources: []\n")
    monkeypatch.setattr(prepare_flatpak, "metainfo_version", lambda root: "0.0.0")

    with pytest.raises(SystemExit):
        prepare_flatpak.main(
            [
                "--lock",
                str(lock),
                "--template",
                str(template),
                "--output-dir",
                str(tmp_path / "out"),
                "--commit",
                "a" * 40,
                "--tag",
                f"v{VERSION}",
            ]
        )


def test_real_template_supports_json_module_references(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.flatpak.toml"
    lock.write_text(
        "[[packages]]\nname = 'example'\nversion = '1'\nwheels = [{ url = 'https://example.invalid/example-1-py3-none-any.whl', hashes = { sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' } }]\n"
        "[[packages]]\nname = 'torch'\nversion = '2.9.1'\nwheels = [{ url = 'https://example.invalid/torch-2.9.1-py3-none-any.whl', hashes = { sha256 = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' } }]\n"
    )
    output = tmp_path / "out"
    assert (
        prepare_flatpak.main(
            [
                "--lock",
                str(lock),
                "--template",
                str(SCRIPT.parents[2] / "packaging/flatpak/io.github.juergenfleiss.aTrain.yml"),
                "--output-dir",
                str(output),
                "--commit",
                "a" * 40,
            ]
        )
        == 0
    )
    assert not (output / "python-build-tools.json").exists()


def test_future_python_and_musl_wheels_cannot_enter_gnome_build() -> None:
    package = {
        "name": "example",
        "version": "1",
        "wheels": [
            artifact("example-1-cp314-cp314-manylinux_2_17_aarch64.whl"),
            artifact("example-1-cp313-cp313-musllinux_1_2_aarch64.whl"),
        ],
    }
    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("aarch64")],
    )
    with pytest.raises(ValueError, match="no supported"):
        prepare_flatpak.choose_download(package, platform)


def test_artifact_without_verified_sha256_is_rejected() -> None:
    package = {
        "name": "example",
        "version": "1",
        "wheels": [artifact("example-1-py3-none-any.whl", "bad")],
    }
    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("x86_64")],
    )
    with pytest.raises(ValueError, match="invalid artifact hash"):
        prepare_flatpak.choose_download(package, platform)


def test_custom_gnome_tags_include_manylinux_242_and_lock_urls_are_deterministic() -> None:
    package = {
        "name": "example",
        "version": "1",
        "wheels": [
            {
                "url": "https://example.invalid/z/example-1-cp313-cp313-manylinux_2_42_x86_64.whl",
                "hashes": {"sha256": "b" * 64},
            },
            {
                "url": "https://example.invalid/a/example-1-cp313-cp313-manylinux_2_42_x86_64.whl",
                "hashes": {"sha256": "a" * 64},
            },
        ],
    }
    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("x86_64")],
    )
    assert "cp313-cp313-manylinux_2_42_x86_64" in platform.python_tags
    assert prepare_flatpak.choose_download(package, platform).sha256 == "a" * 64


def test_malformed_locked_wheel_has_a_clear_error() -> None:
    platform = prepare_flatpak.req2flatpak.Platform(
        python_version=["3", "13"],
        python_tags=[str(tag) for tag in prepare_flatpak.target_tags("x86_64")],
    )
    with pytest.raises(ValueError, match="invalid wheel filename"):
        prepare_flatpak.choose_download(
            {
                "name": "example",
                "version": "1",
                "wheels": [artifact("not-a-wheel.whl")],
            },
            platform,
        )

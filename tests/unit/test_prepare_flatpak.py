from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

# Generator-only dependencies; CI's unit job installs them. 26.3 accepts
# PyTorch's URL-escaped wheel names.
pytest.importorskip("packaging", minversion="26.3")
pytest.importorskip("ruamel.yaml")
from packaging.pylock import Pylock
from packaging.utils import parse_wheel_filename
from ruamel.yaml import YAML

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "prepare_flatpak", ROOT / ".github/scripts/prepare-flatpak.py"
)
prepare_flatpak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_flatpak)


def lock(*packages: dict) -> Pylock:
    return Pylock.from_dict(
        {"lock-version": "1.0", "created-by": "test", "packages": list(packages)}
    )


def test_uv_lock_generates_flathub_sources(tmp_path: Path, capsys) -> None:
    """Every locked dependency must resolve to a pinned wheel on both arches."""
    version, _ = prepare_flatpak.release_version(None)
    prepare_flatpak.main(["--tag", f"v{version}", "--output-dir", str(tmp_path)])
    assert capsys.readouterr().out.splitlines() == [f"version={version}", "stable=true"]

    dependencies = json.loads((tmp_path / "atrain_python_dependencies.json").read_text())
    for module, arch in zip(dependencies["modules"], prepare_flatpak.ARCHES, strict=True):
        assert module["only-arches"] == [arch]
        urls = [source["url"] for source in module["sources"]]
        assert any("/torch-" in url for url in urls)
        assert all(url.startswith("https://") for url in urls)
        if arch == "aarch64":
            wheels = [
                (filename, parse_wheel_filename(filename))
                for url in urls
                if (filename := Path(unquote(urlsplit(url).path)).name).endswith(".whl")
            ]
            cuda_wheels = [
                filename for filename, (_, version, _, _) in wheels if "+cu" in str(version)
            ]
            nvidia_wheels = [
                filename for filename, (name, _, _, _) in wheels if str(name).startswith("nvidia-")
            ]
            assert not cuda_wheels, f"aarch64 output includes CUDA wheels: {cuda_wheels}"
            assert not nvidia_wheels, f"aarch64 output includes NVIDIA wheels: {nvidia_wheels}"

    def atrain_source(manifest: str) -> dict:
        modules = YAML(typ="safe").load(tmp_path / manifest)["modules"]
        [atrain] = [m for m in modules if isinstance(m, dict) and m["name"] == "atrain"]
        return atrain["sources"][0]

    flathub = atrain_source(f"{prepare_flatpak.APP_ID}.yml")
    assert flathub["type"] == "git"
    assert flathub["tag"] == f"v{version}"
    assert len(flathub["commit"]) == 40
    local = atrain_source("local.yml")
    assert local["type"] == "dir"
    assert ".git" in local["skip"]


def test_escaped_wheel_is_staged_under_its_real_filename() -> None:
    wheel = "example-1%2Bcu128-cp313-cp313-manylinux_2_28_aarch64.whl"
    package = {
        "name": "example",
        "version": "1+cu128",
        "wheels": [{"url": f"https://example.invalid/{wheel}", "hashes": {"sha256": "a" * 64}}],
    }
    [source] = prepare_flatpak.python_module(lock(package), "aarch64")["sources"]
    assert source["dest-filename"] == "example-1+cu128-cp313-cp313-manylinux_2_28_aarch64.whl"


@pytest.mark.parametrize(("name", "allowed"), [("proxy-tools", True), ("unreviewed", False)])
def test_sdists_are_limited_to_the_allowlist(name: str, allowed: bool) -> None:
    sdist = {"url": f"https://example.invalid/{name}-1.tar.gz", "hashes": {"sha256": "a" * 64}}
    packages = lock({"name": name, "version": "1", "sdist": sdist})
    if allowed:
        prepare_flatpak.python_module(packages, "x86_64")
    else:
        with pytest.raises(ValueError, match=r"no CPython 3\.13 wheel"):
            prepare_flatpak.python_module(packages, "x86_64")


def test_rc_tags_are_unstable_builds_of_the_upcoming_release() -> None:
    # RC tags keep aTrain/version.py at the upcoming release.
    version, _ = prepare_flatpak.release_version(None)
    assert prepare_flatpak.release_version(f"v{version}") == (version, True)
    assert prepare_flatpak.release_version(f"v{version}-rc3") == (f"{version}rc3", False)


@pytest.mark.parametrize("tag", ["v{v}.post1", "{v}", "v0.0.0", "v0.0.0-rc1", "vnot-a-version"])
def test_mismatched_or_invalid_tags_are_rejected(tag: str) -> None:
    version, _ = prepare_flatpak.release_version(None)
    with pytest.raises(SystemExit):
        prepare_flatpak.release_version(tag.format(v=version))

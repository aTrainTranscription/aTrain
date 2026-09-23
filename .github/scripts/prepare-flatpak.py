#!/usr/bin/env python3
"""Generate the Flathub manifest and offline Python sources from uv.lock.

Writes to the output directory:
  io.github.juergenfleiss.aTrain.yml  Flathub manifest, pinned to the git commit
  local.yml                           the same manifest, built from this checkout
  atrain_python_dependencies.json     per-architecture wheels for pip

and prints version=/stable= lines for $GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from packaging.pylock import PackageWheel, Pylock
from packaging.tags import compatible_tags, cpython_tags
from packaging.version import InvalidVersion, Version
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.juergenfleiss.aTrain"
TEMPLATE = ROOT / "packaging" / "flatpak" / f"{APP_ID}.yml"
ARCHES = ("x86_64", "aarch64")
# The GNOME 50 runtime ships CPython 3.13.15 and glibc 2.42.
PYTHON = (3, 13)
PYTHON_FULL = "3.13.15"
GLIBC_MINOR = 42
MANYLINUX_ALIASES = {17: "2014", 12: "2010", 5: "1"}
# Reviewed pure-Python packages that publish no wheel.
ALLOWED_SDISTS = {"proxy-tools"}
EXPORT = [
    "uv", "export", "--locked", "--extra", "gui", "--no-dev", "--no-emit-project",
    "--format", "pylock.toml",
    # The GNOME runtime provides the GObject bindings.
    "--no-emit-package", "pycairo", "--no-emit-package", "pygobject",
    "--no-emit-package", "pygobject-stubs",
]  # fmt: skip


def target(arch: str) -> tuple[dict[str, str], list]:
    """Marker environment and wheel tags of the GNOME runtime on *arch*."""
    environment = {
        "implementation_name": "cpython",
        "implementation_version": PYTHON_FULL,
        "os_name": "posix",
        "platform_machine": arch,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": PYTHON_FULL,
        "python_version": "3.13",
        "sys_platform": "linux",
    }
    platforms = []
    for minor in range(GLIBC_MINOR, 4, -1):
        platforms.append(f"manylinux_2_{minor}_{arch}")
        if minor in MANYLINUX_ALIASES:
            platforms.append(f"manylinux{MANYLINUX_ALIASES[minor]}_{arch}")
    platforms.append(f"linux_{arch}")
    tags = [
        *cpython_tags(PYTHON, ["cp313"], platforms),
        *compatible_tags(PYTHON, "cp313", platforms),
    ]
    return environment, tags


def python_module(lock: Pylock, arch: str) -> dict:
    environment, tags = target(arch)
    names, sources = [], []
    for package, dist in lock.select(environment=environment, tags=tags):
        if not isinstance(dist, PackageWheel) and package.name not in ALLOWED_SDISTS:
            raise ValueError(f"{package.name} has no CPython 3.13 wheel for {arch}")
        source = {"type": "file", "url": dist.url, "sha256": dist.hashes["sha256"]}
        # pip rejects escaped wheel names, e.g. PyTorch's torch-2.9.1%2Bcu128-....
        if dist.filename != dist.url.rpartition("/")[2]:
            source["dest-filename"] = dist.filename
        names.append(package.name)
        sources.append(source)
    return {
        "name": f"python3-dependencies-{arch}",
        "only-arches": [arch],
        "buildsystem": "simple",
        "build-commands": [
            'pip3 install --no-index --find-links="file://${PWD}" --prefix=${FLATPAK_DEST} '
            "--no-build-isolation --no-deps --ignore-installed " + " ".join(names)
        ],
        "sources": sources,
    }


def release_version(tag: str | None) -> tuple[str, bool]:
    """Release version and whether it is stable, checked against the sources.

    The tag must name aTrain/version.py and the newest AppStream release, or be a
    pre-release of it: RC tags (v1.5.0-rc1) test the upcoming release.
    """
    code = (ROOT / "aTrain" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', code)
    if match is None:
        raise SystemExit("aTrain/version.py defines no __version__")
    metainfo = ROOT / "share" / "metainfo" / f"{APP_ID}.metainfo.xml"
    release = ET.parse(metainfo).find("releases/release")  # noqa: S314 - tracked file
    if release is None or release.get("version") is None:
        raise SystemExit(f"{metainfo.name} has no <release>")
    if tag and not tag.startswith("v"):
        raise SystemExit(f"tag {tag} must start with v, e.g. v{match[1]}")
    try:
        project, newest = Version(match[1]), Version(release.get("version"))
        version = Version(tag.removeprefix("v")) if tag else project
    except InvalidVersion as error:
        raise SystemExit(error) from error
    if newest != project:
        raise SystemExit(f"newest AppStream release {newest} != aTrain/version.py {project}")
    if version != project and not (
        version.is_prerelease and version.base_version == project.base_version
    ):
        raise SystemExit(f"tag {tag} does not match aTrain/version.py {project}")
    return str(version), not version.is_prerelease


def ignored_paths() -> list[str]:
    """Git-ignored paths (venvs, build outputs, bundles) that local builds skip."""
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"],  # noqa: S607
        cwd=ROOT,
        text=True,
    )
    return [".git", *(path.rstrip("/") for path in output.split("\0") if path)]


def write_manifest(path: Path, source: dict) -> None:
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.preserve_quotes = True
    yaml.width = 4096
    manifest = yaml.load(TEMPLATE)
    [atrain] = [m for m in manifest["modules"] if isinstance(m, dict) and m["name"] == "atrain"]
    atrain["sources"][0] = source
    yaml.dump(manifest, path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tag", help="release tag, e.g. v1.5.0")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "flatpak-release")
    args = parser.parse_args(argv)

    version, stable = release_version(args.tag)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()  # noqa: S607
    lock = Pylock.from_dict(tomllib.loads(subprocess.check_output(EXPORT, cwd=ROOT, text=True)))

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    dependencies = {
        "name": "python3-dependencies",
        "buildsystem": "simple",
        "build-commands": [],
        "modules": [python_module(lock, arch) for arch in ARCHES],
    }
    (out / "atrain_python_dependencies.json").write_text(
        json.dumps(dependencies, indent=2) + "\n", encoding="utf-8"
    )
    tag = {"tag": args.tag} if args.tag else {}
    write_manifest(
        out / f"{APP_ID}.yml",
        {
            "type": "git",
            "url": "https://github.com/aTrainTranscription/aTrain.git",
            **tag,
            "commit": commit,
        },
    )
    write_manifest(
        out / "local.yml",
        {"type": "dir", "path": os.path.relpath(ROOT, out.resolve()), "skip": ignored_paths()},
    )
    print(f"version={version}")
    print(f"stable={str(stable).lower()}")


if __name__ == "__main__":
    main()

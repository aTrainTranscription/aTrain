#!/usr/bin/env python3
"""Create the architecture-specific, offline Python sources for Flatpak."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import req2flatpak
import yaml
from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

APP_ID = "io.github.juergenfleiss.aTrain"
ALLOWED_SDISTS = {"julius", "proxy-tools"}
LOCAL_SOURCE_SKIPS = [
    ".git",
    ".venv",
    ".flatpak-work",
    ".flatpak-builder",
    "flatpak_app",
    "repo",
    "data",
    "dist",
    "build",
]
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def target_tags(arch: str):
    # Tell req2flatpak which CPython 3.13 wheels can run on the GNOME 50 runtime.
    platforms = [f"manylinux_2_{minor}_{arch}" for minor in range(42, 16, -1)]
    platforms += [
        f"manylinux2014_{arch}",
        f"manylinux2010_{arch}",
        f"manylinux1_{arch}",
        f"linux_{arch}",
    ]
    return list(cpython_tags((3, 13), abis=["cp313"], platforms=platforms)) + list(
        compatible_tags((3, 13), interpreter="cp313", platforms=platforms)
    )


def marker_environment(arch: str) -> dict[str, str]:
    # Evaluate requirement markers as Linux/Python 3.13 on the target architecture.
    environment = default_environment()
    environment.update(
        implementation_name="cpython",
        implementation_version="3.13.0",
        os_name="posix",
        platform_machine=arch,
        platform_python_implementation="CPython",
        platform_release="",
        platform_system="Linux",
        platform_version="",
        python_full_version="3.13.0",
        python_version="3.13",
        sys_platform="linux",
    )
    return environment


def lock_packages(lock: Path, arch: str) -> dict[tuple[str, str], dict]:
    # pylock.toml contains the selected dependency set, markers, and artifacts.
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], dict] = {}
    for package in data.get("packages", []):
        marker = package.get("marker")
        if marker and not Marker(marker).evaluate(marker_environment(arch)):
            continue
        if "name" not in package or "version" not in package:
            raise ValueError("pylock package is missing name or version")
        key = (canonicalize_name(package["name"]), package["version"])
        if key in result:
            raise ValueError(f"ambiguous lock entries for {key[0]} {key[1]}")
        result[key] = package
    return dict(sorted(result.items()))


def valid_artifact(artifact: dict) -> None:
    # Every source passed to Flatpak must have an HTTPS URL and locked SHA-256.
    url, digest = artifact.get("url"), artifact.get("hash")
    if not isinstance(url, str) or urlparse(url).scheme != "https":
        raise ValueError(f"unsupported artifact URL: {url!r}")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"invalid artifact hash for {url}")


def release_from_lock(package: dict) -> req2flatpak.Release:
    """Adapt uv's locked artifacts into req2flatpak's offline release model."""
    name = canonicalize_name(package["name"])
    version = package["version"]
    artifacts = list(package.get("wheels", []))
    if isinstance(package.get("sdist"), dict):
        artifacts.append(package["sdist"])
    # Construct req2flatpak objects ourselves so it never needs to query PyPI.
    downloads = []
    for artifact in artifacts:
        normalized = {
            "url": artifact.get("url"),
            "hash": f"sha256:{artifact.get('hashes', {}).get('sha256')}",
        }
        valid_artifact(normalized)
        url = normalized["url"]
        filename = unquote(Path(urlparse(url).path).name)
        if not filename:
            raise ValueError(f"artifact URL has no filename: {url}")
        download = req2flatpak.Download(
            package=name,
            version=version,
            filename=filename,
            url=url,
            sha256=normalized["hash"].removeprefix("sha256:"),
        )
        if download.is_wheel:
            try:
                # Force parsing now so malformed locked wheel diagnostics are explicit.
                _ = download.tags
            except ValueError as error:
                raise ValueError(f"invalid wheel filename: {url}") from error
        downloads.append(download)
    return req2flatpak.Release(name, version, sorted(downloads, key=lambda item: item.url))


def choose_download(package: dict, platform: req2flatpak.Platform) -> req2flatpak.Download:
    release = release_from_lock(package)
    # Let req2flatpak select the best compatible wheel from uv's locked candidates.
    wheel = req2flatpak.DownloadChooser.wheel(release, platform)
    if wheel is not None:
        return wheel
    # Source builds are allowed only for the small, reviewed build-tool allowlist.
    if release.package not in ALLOWED_SDISTS:
        raise ValueError(f"no supported CPython 3.13 Linux wheel for {release.package}")
    sdist = req2flatpak.DownloadChooser.sdist(release)
    if sdist is None:
        raise ValueError(f"approved source package has no sdist: {release.package}")
    return sdist


def python_module(arch: str, packages: dict[tuple[str, str], dict]) -> dict:
    # Supply our GNOME 50 tags instead of req2flatpak's older built-in Linux target.
    platform = req2flatpak.Platform(
        python_version=["3", "13"], python_tags=[str(tag) for tag in target_tags(arch)]
    )
    selected_requirements = []
    downloads = []
    for (name, version), package in packages.items():
        selected_requirements.append(req2flatpak.Requirement(package=name, version=version))
        downloads.append(choose_download(package, platform))
    # req2flatpak creates the module and source list; pip may use only those files.
    module = req2flatpak.FlatpakGenerator.build_module(
        selected_requirements,
        downloads,
        module_name=f"python-dependencies-{'x86-64' if arch == 'x86_64' else 'aarch64'}",
        pip_install_template=(
            "pip install --no-index --find-links=file://${PWD} --prefix=${FLATPAK_DEST} "
            "--no-build-isolation --no-deps --ignore-installed "
        ),
    )
    module["only-arches"] = [arch]
    return module


def source_version(root: Path) -> str:
    match = re.search(
        r'__version__\s*=\s*"([^"]+)"', (root / "aTrain/version.py").read_text()
    )
    if match is None:
        raise ValueError("aTrain/version.py has no __version__")
    return match.group(1)


def metainfo_version(root: Path) -> str:
    source = root / "share" / "metainfo" / f"{APP_ID}.metainfo.xml"
    tree = ET.parse(source)  # noqa: S314 - this is a tracked project metadata file.
    releases = tree.getroot().find("releases")
    if releases is None:
        raise ValueError("AppStream metadata has no releases")
    release = next((item for item in releases if item.tag == "release"), None)
    if release is None or not release.get("version"):
        raise ValueError("AppStream metadata has no release version")
    return release.get("version")


def update_manifest(
    template: Path, output: Path, commit: str, tag: str | None, local_source: Path | None
) -> None:
    manifest = yaml.safe_load(template.read_text(encoding="utf-8"))
    module = next(
        (
            item
            for item in manifest.get("modules", [])
            if isinstance(item, dict) and item.get("name") == "atrain"
        ),
        None,
    )
    if module is None:
        raise ValueError("template has no atrain module")
    source = (
        {"type": "dir", "path": str(local_source.resolve()), "skip": LOCAL_SOURCE_SKIPS}
        if local_source
        else {
            "type": "git",
            "url": "https://github.com/aTrainTranscription/aTrain.git",
            "commit": commit,
        }
    )
    if tag and not local_source:
        source["tag"] = tag
    module["sources"] = [
        source,
    ]
    output.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lock", type=Path, required=True, help="uv export --format pylock.toml output"
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("packaging/flatpak/io.github.juergenfleiss.aTrain.yml"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--local-source", type=Path)
    args = parser.parse_args(argv)
    if not COMMIT_RE.fullmatch(args.commit):
        parser.error("--commit must be 40 lowercase hexadecimal characters")
    root = Path(__file__).resolve().parents[2]
    project_version = source_version(root)
    version = project_version
    if args.tag:
        tag_version = args.tag[1:] if args.tag.startswith("v") else ""
        try:
            Version(tag_version)
        except InvalidVersion:
            parser.error("--tag must be vVERSION")
        version = tag_version
        if project_version != version:
            parser.error(
                "tag version must match aTrain/version.py "
                f"({version!r} != {project_version!r})"
            )
    metadata_version = metainfo_version(root)
    if metadata_version != version:
        parser.error(
            "newest AppStream release must match the release version "
            f"({metadata_version!r} != {version!r})"
        )
    if args.local_source and not args.local_source.is_dir():
        parser.error("--local-source must be an existing directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    packages = {arch: lock_packages(args.lock, arch) for arch in ("x86_64", "aarch64")}
    # Generate independent dependency modules because markers and wheels differ by CPU.
    modules = [python_module(arch, packages[arch]) for arch in ("x86_64", "aarch64")]
    (args.output_dir / "atrain_python_dependencies.json").write_text(
        json.dumps(
            {
                "name": "python-dependencies",
                "buildsystem": "simple",
                "build-commands": ["true"],
                "modules": modules,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # The pinned source contains the versioned AppStream metadata.
    update_manifest(
        args.template,
        args.output_dir / args.template.name,
        args.commit,
        args.tag,
        args.local_source,
    )
    (args.output_dir / "flathub.json").write_text(
        json.dumps({"only-arches": ["x86_64", "aarch64"]}, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

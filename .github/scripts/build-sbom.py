#!/usr/bin/env python3
"""Turn a raw `cyclonedx-py environment` document into the release SBOM.

Runs once per build job, because an SBOM describes one artifact: the Windows
installer carries torch+cu128 while a Flatpak or macOS build resolves to a
different set. Hence the platform in the output name.

    uvx --from cyclonedx-bom cyclonedx-py environment .venv -o raw.json
    .github/scripts/build-sbom.py --input raw.json --version 1.5.0 \
        --platform windows --output aTrain-1.5.0-windows.cdx.json

The inventory comes from the installed environment rather than the lockfile:
that is what actually ended up in the artifact, and it carries the licence
metadata the lockfile has no room for. Generating it separately keeps this
script free of the tool - and keeps `cyclonedx-bom` out of the environment it
is inventorying, where it would otherwise show up as a component of aTrain.

Three things are added on top:

  * `metadata.component`, which cyclonedx-py leaves empty, so the document
    states what it is an SBOM *of*. aTrain is already in the component list
    with its dependency graph, so it is promoted rather than invented - the
    graph then hangs off the root instead of floating.
  * the ML models, which no Python tool can see: they are downloaded at
    runtime, not installed as packages. CycloneDX 1.6 has a component type
    for them, and purl a `huggingface` type whose version is the revision
    commit - exactly what models.json pins.
  * who supplies the software and who produced the document, neither of which
    can be read off an environment - and both are baseline fields for an SBOM
    (they are on the NTIA minimum-elements list).

Package and model hashes are deliberately left out. uv.lock records a sha256
per distribution and models.json one per model file; both are in the
repository, both are enforced at install and download time. Restating them
here would duplicate a control rather than add one. The SBOM's job is
inventory: what is in the release, at which version, under which licence.

`--validate` checks the result against the CycloneDX 1.6 schema and needs
`cyclonedx-python-lib[json-validation]`; the release workflow supplies it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_JSON = REPO_ROOT / "aTrain_core" / "data" / "models.json"

# The version this script writes and validates against. Pinned rather than
# taken from the input: the generator emits the newest version it supports, so
# a bumped `CYCLONEDX_BOM` would otherwise change the document under a release.
SPEC_VERSION = "1.6"

# Named without an address: this document is published with the release, and
# the maintainers' mail addresses have no business travelling with it.
SUPPLIER = {"name": "aTrain project", "url": ["https://github.com/aTrainTranscription/aTrain"]}


def promote_root(sbom: dict, version: str, platform: str) -> str:
    """Move the aTrain component into `metadata.component` and return its ref.

    The environment SBOM lists aTrain like any other installed distribution.
    Promoting that entry instead of writing a fresh one keeps its `bom-ref`,
    and with it the dependency graph that already points at its direct
    dependencies - a hand-made root would be a leaf with no edges.
    """
    root = next((c for c in sbom["components"] if c["name"].lower() == "atrain"), None)
    if root is None:
        sys.exit(
            "error: no aTrain component in the input - the environment was inventoried "
            "before the project was installed into it, so the SBOM would describe only "
            "its dependencies."
        )
    sbom["components"].remove(root)

    # The version comes from the release, not from the environment: test builds
    # run with a dispatch version string that no pyproject.toml carries.
    if root.get("version") != version:
        print(f"note: installed version {root.get('version')} labelled as {version}")
    root["version"] = version
    root["type"] = "application"
    root["properties"] = [{"name": "atrain:build:platform", "value": platform}]
    # TODO: add the pypi purl once aTrain is published there.
    # PackageSource: Local, i.e. the checkout on the runner - meaningless once
    # the SBOM leaves it, and it leaks the build path.
    root.pop("externalReferences", None)

    sbom["metadata"]["component"] = root
    return root["bom-ref"]


def model_components(models: dict, bundled: set[str]) -> list[dict]:
    """Describe each model as its own component.

    purl's `huggingface` type identifies a model repository, and its version
    is the revision commit - which is what models.json pins and what
    `snapshot_download` is called with, so the SBOM names the same immutable
    thing the app fetches.

    `scope` says the same thing as the delivery property below, but in the
    field a consumer's tooling already reads: a model that is not inside the
    installer cannot be called until it has been downloaded. Without it a slim
    build reads as one that ships 20 GB of models.
    """
    components = []
    for name, model in sorted(models.items()):
        namespace, _, repo = model["repo_id"].partition("/")
        revision = model["revision"]
        components.append(
            {
                "type": "machine-learning-model",
                "bom-ref": f"model:{name}@{revision}",
                "group": namespace,
                "name": repo,
                "version": revision,
                "scope": "required" if name in bundled else "optional",
                "purl": f"pkg:huggingface/{namespace}/{repo}@{revision}",
                "description": f"aTrain model '{name}' ({model['repo_size_human']})",
                # `declared`: this is what the model card of the repository we
                # pin states, not the result of an audit of the weights. An id
                # the SPDX list does not know fails --validate.
                "licenses": [{"license": {"id": model["license"], "acknowledgement": "declared"}}],
                "externalReferences": [
                    {"type": "distribution", "url": f"https://huggingface.co/{model['repo_id']}"}
                ],
                "properties": [
                    {
                        "name": "atrain:model:delivery",
                        # Bundled builds ship the required models inside the
                        # installer; otherwise they are fetched on first use.
                        "value": "bundled" if name in bundled else "on-demand",
                    }
                ],
            }
        )
    return components


def validate(document: str) -> None:
    """Check the document against the CycloneDX 1.6 schema.

    Everything above edits the JSON by hand, so nothing else would notice a
    document that stops conforming - an SBOM a consumer's tooling rejects is
    worth as much as no SBOM at all.
    """
    try:
        # cyclonedx defers this import to the first validation call and turns a
        # failure into an exception of its own, so probe the backend here to
        # keep a missing extra from surfacing as a traceback mid-run.
        import jsonschema  # noqa: F401
        from cyclonedx.schema import SchemaVersion
        from cyclonedx.validation.json import JsonStrictValidator
    except ImportError:
        sys.exit(
            "error: --validate needs cyclonedx-python-lib[json-validation]; run this via "
            "`uv run --no-project --with 'cyclonedx-python-lib[json-validation]'`"
        )
    if error := JsonStrictValidator(SchemaVersion.V1_6).validate_str(document):
        sys.exit(f"error: the SBOM does not conform to CycloneDX 1.6: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path, help="raw cyclonedx-py output")
    parser.add_argument("--output", required=True, type=Path, help="file to write")
    parser.add_argument("--version", required=True, help="release version, e.g. 1.5.0")
    parser.add_argument("--platform", required=True, help="artifact platform, e.g. windows")
    parser.add_argument(
        "--bundled-models",
        default="",
        help="comma-separated models shipped inside the artifact (default: none)",
    )
    parser.add_argument(
        "--validate", action="store_true", help="check the result against the CycloneDX schema"
    )
    args = parser.parse_args()

    sbom = json.loads(args.input.read_text())
    # Not covered by --validate: the 1.6 schema happily accepts a document
    # labelled 1.5, so a changed generator would go unnoticed until a consumer
    # rejects the release asset.
    if sbom["specVersion"] != SPEC_VERSION:
        sys.exit(f"error: the input is CycloneDX {sbom['specVersion']}, not {SPEC_VERSION}")

    root_ref = promote_root(sbom, args.version, args.platform)
    # Who supplies the software, and who produced this document: the generator
    # records only itself, under `metadata.tools`, which names a tool and not
    # an author.
    sbom["metadata"]["supplier"] = SUPPLIER
    sbom["metadata"]["authors"] = [{"name": SUPPLIER["name"]}]

    models = json.loads(MODELS_JSON.read_text())
    bundled = {name for name in args.bundled_models.split(",") if name}
    if unknown := bundled - models.keys():
        sys.exit(f"error: --bundled-models names models that are not in models.json: {unknown}")
    # A model added without a licence would otherwise be the one component in
    # the document that says nothing about its terms - and the models are the
    # part no other tool inventories at all.
    if unlicensed := sorted(name for name, model in models.items() if not model.get("license")):
        sys.exit(f"error: models.json carries no license for: {', '.join(unlicensed)}")

    components = model_components(models, bundled)
    sbom["components"].extend(components)

    # Hang the models off the root as well, so they are reachable in the
    # dependency graph rather than only listed. They pull in nothing
    # themselves, which an empty `dependsOn` states explicitly - CycloneDX
    # reads a missing entry as "unknown" instead.
    refs = [c["bom-ref"] for c in components]
    dependencies = {entry["ref"]: entry for entry in sbom["dependencies"]}
    # `dependsOn` is optional and cyclonedx omits it for components it found no
    # edges for, so the existing edges have to be read defensively rather than
    # indexed - a root installed with --no-deps has an entry but no key.
    existing = dependencies.get(root_ref, {}).get("dependsOn", [])
    dependencies[root_ref] = {"ref": root_ref, "dependsOn": sorted(existing + refs)}
    for ref in refs:
        dependencies[ref] = {"ref": ref, "dependsOn": []}
    sbom["dependencies"] = sorted(dependencies.values(), key=lambda entry: entry["ref"])

    document = json.dumps(sbom, indent=2) + "\n"
    if args.validate:
        validate(document)
    args.output.write_text(document)
    print(
        f"{args.output}: {len(sbom['components'])} components "
        f"({len(components)} models, {len(bundled)} of them bundled)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

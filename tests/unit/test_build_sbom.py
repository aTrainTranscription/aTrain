"""Unit tests for the release SBOM builder.

The generator itself (`cyclonedx-py environment`) is not exercised here - it
needs a populated virtual environment and is covered by the `sbom` CI job.
What these cover is the part we wrote: promoting aTrain to the document root,
turning models.json into components, and keeping the dependency graph intact.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "build-sbom.py"


def load_script():
    """Import the script by path - its name is a command, not an identifier."""
    spec = importlib.util.spec_from_file_location("build_sbom", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_sbom = load_script()


@pytest.fixture
def raw_sbom():
    """A cyclonedx-py environment document, trimmed to what we touch."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"timestamp": "2026-08-13T00:00:00Z"},
        "components": [
            {
                "bom-ref": "aTrain==1.5.0",
                "name": "aTrain",
                "version": "1.5.0",
                "type": "library",
                "externalReferences": [
                    {"type": "distribution", "url": "file:///home/someone/b310/aTrain"}
                ],
            },
            {
                "bom-ref": "torch==2.9.1",
                "name": "torch",
                "version": "2.9.1",
                "type": "library",
            },
        ],
        "dependencies": [
            {"ref": "aTrain==1.5.0", "dependsOn": ["torch==2.9.1"]},
            {"ref": "torch==2.9.1", "dependsOn": []},
        ],
    }


@pytest.fixture
def models():
    return {
        "tiny": {
            "repo_id": "aTrain-core/faster-whisper-tiny",
            "revision": "67ab6c7e",
            "license": "MIT",
            "repo_size_human": "75.54 MB",
        },
        "speaker-detection": {
            "repo_id": "aTrain-core/speaker-detection",
            "revision": "027e7a80",
            "license": "CC-BY-4.0",
            "repo_size_human": "32.1 MB",
        },
    }


def build(tmp_path, raw_sbom, **overrides):
    """Run the script end to end and return the parsed result."""
    source = tmp_path / "raw.json"
    source.write_text(json.dumps(raw_sbom))
    output = tmp_path / "out.json"
    argv = {
        "--input": str(source),
        "--output": str(output),
        "--version": "1.5.0",
        "--platform": "windows",
        **overrides,
    }
    return output, [item for pair in argv.items() for item in pair]


# --- promoting aTrain to the document root ---------------------------------


def test_the_root_component_is_the_promoted_atrain_entry(raw_sbom):
    build_sbom.promote_root(raw_sbom, "1.6.0", "windows")

    root = raw_sbom["metadata"]["component"]
    assert root["name"] == "aTrain"
    assert root["type"] == "application"
    assert root["version"] == "1.6.0"
    assert root["properties"] == [{"name": "atrain:build:platform", "value": "windows"}]
    # aTrain is not on PyPI, so no purl is invented for it.
    assert "purl" not in root


def test_the_promoted_component_leaves_the_component_list(raw_sbom):
    build_sbom.promote_root(raw_sbom, "1.5.0", "windows")

    assert [c["name"] for c in raw_sbom["components"]] == ["torch"]


def test_promoting_keeps_the_dependency_graph_pointing_at_the_root(raw_sbom):
    # The whole reason for promoting rather than writing a fresh root: a
    # hand-made component would have a bom-ref nothing refers to, leaving the
    # 16 direct dependencies dangling.
    ref = build_sbom.promote_root(raw_sbom, "1.5.0", "windows")

    assert ref == "aTrain==1.5.0"
    edge = next(e for e in raw_sbom["dependencies"] if e["ref"] == ref)
    assert edge["dependsOn"] == ["torch==2.9.1"]


def test_the_local_build_path_is_dropped(raw_sbom):
    # cyclonedx records the checkout directory as the package source, which is
    # both meaningless outside the runner and a needless leak of its layout.
    build_sbom.promote_root(raw_sbom, "1.5.0", "windows")

    assert "externalReferences" not in raw_sbom["metadata"]["component"]


def test_an_environment_without_atrain_is_refused(raw_sbom):
    # Inventorying before the project is installed would produce a plausible
    # looking SBOM that describes only the dependencies.
    raw_sbom["components"] = [c for c in raw_sbom["components"] if c["name"] != "aTrain"]

    with pytest.raises(SystemExit) as excinfo:
        build_sbom.promote_root(raw_sbom, "1.5.0", "windows")
    assert "no aTrain component" in str(excinfo.value)


@pytest.mark.parametrize("name", ["aTrain", "atrain", "ATRAIN"])
def test_the_project_is_found_regardless_of_how_its_name_is_cased(raw_sbom, name):
    raw_sbom["components"][0]["name"] = name

    build_sbom.promote_root(raw_sbom, "1.5.0", "windows")

    assert raw_sbom["metadata"]["component"]["name"] == name


# --- models as components --------------------------------------------------


def test_each_model_becomes_a_machine_learning_component(models):
    components = build_sbom.model_components(models, bundled=set())

    assert len(components) == len(models)
    assert {c["type"] for c in components} == {"machine-learning-model"}


def test_the_purl_pins_the_revision_commit(models):
    tiny = next(c for c in build_sbom.model_components(models, set()) if "tiny" in c["purl"])

    assert tiny["purl"] == "pkg:huggingface/aTrain-core/faster-whisper-tiny@67ab6c7e"
    assert tiny["version"] == "67ab6c7e"
    assert tiny["group"] == "aTrain-core"


def test_bundled_models_are_told_apart_from_downloaded_ones(models):
    components = build_sbom.model_components(models, bundled={"speaker-detection"})

    delivery = {
        component["name"]: prop["value"]
        for component in components
        for prop in component["properties"]
        if prop["name"] == "atrain:model:delivery"
    }
    assert delivery == {"speaker-detection": "bundled", "faster-whisper-tiny": "on-demand"}


def test_a_downloaded_model_is_scoped_optional_and_a_bundled_one_required(models):
    # `atrain:model:delivery` is ours and invisible to a consumer's tooling.
    # Without `scope`, a slim installer reads as one that ships 20 GB of models.
    scope = {
        component["name"]: component["scope"]
        for component in build_sbom.model_components(models, bundled={"speaker-detection"})
    }

    assert scope == {"speaker-detection": "required", "faster-whisper-tiny": "optional"}


def test_the_model_licence_is_the_one_models_json_pins(models):
    tiny = next(c for c in build_sbom.model_components(models, set()) if "tiny" in c["name"])

    assert tiny["licenses"] == [{"license": {"id": "MIT", "acknowledgement": "declared"}}]


# --- the shipped models.json -----------------------------------------------


def test_the_real_models_file_produces_a_component_for_every_model():
    models = json.loads(build_sbom.MODELS_JSON.read_text())
    components = build_sbom.model_components(models, bundled=set())

    assert len(components) == len(models)
    # A model added without a repo_id or revision would otherwise reach the
    # release as a component with a malformed purl.
    for component in components:
        assert component["purl"].startswith("pkg:huggingface/aTrain-core/")
        assert component["version"]


def test_every_shipped_model_declares_a_licence():
    # The models are the only part of the release no other tool inventories,
    # so a model added without a licence has to fail here rather than reach a
    # release as the one component that states nothing about its terms.
    models = json.loads(build_sbom.MODELS_JSON.read_text())

    assert all(model.get("license") for model in models.values())


# --- the assembled document ------------------------------------------------


def test_the_models_hang_off_the_root_in_the_dependency_graph(tmp_path, raw_sbom, monkeypatch):
    output, argv = build(tmp_path, raw_sbom)
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    build_sbom.main()

    result = json.loads(output.read_text())
    graph = {e["ref"]: e["dependsOn"] for e in result["dependencies"]}
    root = result["metadata"]["component"]["bom-ref"]
    model_refs = [c["bom-ref"] for c in result["components"] if c["bom-ref"].startswith("model:")]

    assert model_refs, "no models in the document"
    assert set(model_refs) <= set(graph[root])
    # Kept alongside the models rather than replaced by them.
    assert "torch==2.9.1" in graph[root]
    # An absent entry reads as "dependencies unknown"; an empty one states
    # that the model pulls in nothing further.
    assert all(graph[ref] == [] for ref in model_refs)


def test_a_root_without_recorded_edges_still_gets_the_models(tmp_path, raw_sbom, monkeypatch):
    # `dependsOn` is optional: cyclonedx writes the entry but omits the key for
    # a component it found no edges for, which is what an environment built
    # with --no-deps looks like.
    raw_sbom["dependencies"] = [{"ref": "aTrain==1.5.0"}]
    output, argv = build(tmp_path, raw_sbom)
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    build_sbom.main()

    result = json.loads(output.read_text())
    graph = {e["ref"]: e["dependsOn"] for e in result["dependencies"]}
    assert len(graph["aTrain==1.5.0"]) == len(json.loads(build_sbom.MODELS_JSON.read_text()))


def test_the_document_names_its_supplier_and_its_author(tmp_path, raw_sbom, monkeypatch):
    # cyclonedx records only itself, under `metadata.tools`, which answers
    # "produced by which tool", not "by whom".
    output, argv = build(tmp_path, raw_sbom)
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    build_sbom.main()

    metadata = json.loads(output.read_text())["metadata"]
    assert metadata["supplier"]["name"] == "aTrain project"
    assert metadata["authors"] == [{"name": "aTrain project"}]


def test_an_input_of_another_spec_version_is_refused(tmp_path, raw_sbom, monkeypatch):
    # The generator writes the newest version it supports, and --validate does
    # not check: the 1.6 schema accepts a document labelled 1.5.
    raw_sbom["specVersion"] = "1.5"
    output, argv = build(tmp_path, raw_sbom)
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    with pytest.raises(SystemExit) as excinfo:
        build_sbom.main()
    assert "1.5" in str(excinfo.value)
    assert not output.exists()


def test_a_model_without_a_licence_is_refused(tmp_path, raw_sbom, models, monkeypatch):
    del models["tiny"]["license"]
    models_json = tmp_path / "models.json"
    models_json.write_text(json.dumps(models))
    monkeypatch.setattr(build_sbom, "MODELS_JSON", models_json)
    output, argv = build(tmp_path, raw_sbom)
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    with pytest.raises(SystemExit) as excinfo:
        build_sbom.main()
    assert "tiny" in str(excinfo.value)
    assert not output.exists()


def test_an_unknown_bundled_model_is_refused(tmp_path, raw_sbom, monkeypatch):
    # A typo here would otherwise silently mark nothing as bundled, and the
    # SBOM would claim the installer downloads models it actually ships.
    output, argv = build(tmp_path, raw_sbom, **{"--bundled-models": "large-v3-turbo,typo"})
    monkeypatch.setattr("sys.argv", ["build-sbom.py", *argv])

    with pytest.raises(SystemExit) as excinfo:
        build_sbom.main()
    assert "typo" in str(excinfo.value)
    assert not output.exists()

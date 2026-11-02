# Proposal: load models from an internal source

Status: proposal, for discussion. Nothing here is implemented yet.

## Problem

Some organisations do not let their clients reach Hugging Face. Their IT
department wants to put the models on an internal web server or a network
share once, and have every aTrain installation load them from there.

Today aTrain can only download from Hugging Face. The workaround is to copy
the model folders onto every machine by hand (see
[Installing models without Hugging Face access](../offline-model-install.md)).
That does not scale, and it is easy to get wrong.

## How aTrain is configured today

There is no configuration file. aTrain reads:

| Setting                                           | Source                                  | Purpose                                             |
| ------------------------------------------------- | --------------------------------------- | --------------------------------------------------- |
| `ATRAIN_USER_DIR`                                 | environment variable                    | location of models, transcripts and settings        |
| `PYANNOTE_METRICS_ENABLED`                        | environment variable, default `false`   | pyannote telemetry                                  |
| `HF_ENDPOINT`, `HF_HUB_OFFLINE`, ...              | environment variables, read by `huggingface_hub` | Hub endpoint, offline mode                 |
| `HTTPS_PROXY`, `REQUESTS_CA_BUNDLE`, ...          | environment variables, read by `requests` | proxy and CA bundle                               |
| `--host`, `--port`, `--native`                    | command-line flags of `aTrain start`    | not reachable when started from the Start menu      |
| model, language, speaker detection, ...           | `Documents\aTrain\settings\` (NiceGUI storage) | the user's last choices in the UI, not meant for admins |

Environment variables can be rolled out by Group Policy and reach the MSIX app.

`HF_ENDPOINT` already redirects all Hub traffic, but only to a server that
speaks the Hugging Face API (for example a Hugging Face remote repository in
Artifactory or Nexus). A plain web server or a network share does not work,
because `snapshot_download` first asks `/api/models/<repo>/revision/<rev>`.

## Proposal

### One setting: `model_source`

- A URL (`https://models.example.org/atrain/`) or a path (`\\fileserver\atrain\models`, `/srv/atrain/models`).
- When it is set, aTrain loads models only from there and never contacts Hugging Face.
- When it is not set, nothing changes.

### Layout at the source

The same layout as a local models folder:

```
<model_source>/
├── large-v3-turbo/
│   ├── .gitattributes
│   ├── config.json
│   └── ...
└── speaker-detection/
    ├── config.yaml
    ├── embedding/pytorch_model.bin
    └── ...
```

IT fills it by copying the models folder of a machine that has the models,
for example after `aTrain init` or after running the script from the offline
install docs. Any static web server or file share can serve it.

### How a model is loaded

`get_model()` keeps its flow. Only `download_model()` gets a second branch:

1. For each file in the model's manifest in `models.json`, fetch
   `<model_source>/<model>/<file>`: copy it for a path, `GET` it for a URL.
2. Write each file under a temporary name and move it into place when it is
   complete, like `huggingface_hub` does.
3. Report byte progress to the existing progress dict.
4. Run the existing `verify_model()` against the pinned checksums.

No Hugging Face API is needed: `models.json` already lists every file and its
SHA-256.

### Where the setting comes from

In this order, the first one found wins:

1. Environment variable `ATRAIN_MODEL_SOURCE`.
2. User file `<ATRAIN_DIR>/config.toml`.
3. Machine file: `%ProgramData%\aTrain\config.toml` on Windows,
   `/etc/atrain/config.toml` on Linux,
   `/Library/Application Support/aTrain/config.toml` on macOS.

```toml
# config.toml
model_source = '\\fileserver\atrain\models'  # literal string, no escaping
```

`tomllib` is in the standard library (Python 3.11+), so no new dependency.
The machine file lets IT configure all users at once; the environment variable
is enough for a first version and for tests.

## Security

- The checksums in `models.json` are pinned in the repository, so a
  compromised or wrong internal source cannot swap the weights: verification
  fails and the files are removed, as today.
- HTTPS is recommended. Plain HTTP on an internal network does not weaken
  integrity, for the same reason.
- Authentication: a network share uses the user's Windows login. Web servers
  that need authentication are out of scope for the first version.
- The "offline by design" rule in `AGENTS.md` and the code signing policy
  ("what the app transmits") need a sentence about the configured source.

## Scope for a first PR

1. `ATRAIN_MODEL_SOURCE` (path or URL) in `aTrain_core/globals.py`.
2. The second branch in `download_model()`.
3. Unit tests: a temp dir as source, and a local `http.server` as source,
   both with a small fake manifest.
4. Docs: a section in `deployment-windows.md` and in `offline-model-install.md`.

The config file follows in a second PR once the behaviour is agreed.

## Open questions

- Should aTrain fall back to Hugging Face when the source does not have a
  model? This proposal says no, so that the setting is a hard guarantee.
- Should the source also hold models that are not in `models.json`? Not in
  this proposal: only pinned models can be verified.
- Should the models page show where models come from?

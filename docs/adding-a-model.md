# Adding a model

aTrain only offers the models listed in
[`aTrain_core/data/models.json`](../aTrain_core/data/models.json). It downloads
them from mirrors under the [aTrain-core](https://huggingface.co/aTrain-core)
organisation on Hugging Face, pinned to a commit, and checks every file against
a pinned hash. Qwen3 ASR and its aligner currently use the official
[Qwen](https://huggingface.co/Qwen) `-hf` repositories as an explicit exception
until mirrors are available. These checkpoints use safetensors and native
Transformers classes; no remote model code is enabled. Adding your own model inside the app is
not supported yet, see
[#72](https://github.com/aTrainTranscription/aTrain/issues/72).

Two roles are involved:

- **Mirroring** needs write access to the aTrain-core organisation, so the
  maintainers do it. To propose a model, open an issue with a link to it.
- **Everything after the mirror** is a normal pull request that anyone can
  prepare: the entry in `models.json`, the pinned hashes and the checks.

## 1. Check the model

- The licence allows us to host a copy, and you know its SPDX identifier.
- The model has an architecture supported by aTrain's faster-whisper or
  Transformers backends.
- The transcription quality of real recordings in its target language is good.
- If the model needs a backend aTrain does not have yet, open a pull request
  first that weighs the cost of the new backend against what the model offers
  over the models that run on the existing backends.

## 2. Mirror it under aTrain-core (maintainers)

Most mirrors are plain copies of models that already come in the
faster-whisper format. Only if a model doesn't, convert it:

```bash
ct2-transformers-converter --model <source repo> --revision <commit> \
  --output_dir <folder> --copy_files tokenizer.json preprocessor_config.json \
  --quantization float16
```

Pin the source with `--revision` so the mirror's README can say exactly what was
converted. A conversion can finish without errors and still degrade the output
badly, so transcribe a few recordings in the target language with the
converted model and compare them with the source model before uploading.

Upload the folder to a new model repo under aTrain-core, add the licence file
and a README naming the source and its commit, and note the commit hash of the
upload. This is done manually by the maintainers.

Every file in the repo gets pinned and downloaded, so keep only these:

| Backend                | Files to keep                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `faster-whisper`       | `config.json`, `model.bin`, `preprocessor_config.json`, `tokenizer.json`, `vocabulary.json` |
| `crisper-transformers` | the transformers files of the source model, see `aTrain-core/CrisperWhisper2_large`         |
| `qwen3-transformers`, `qwen3-aligner` | the native `-hf` checkpoint's safetensors, config, processor, tokenizer and chat-template files |
| all                    | `.gitattributes` (created by the Hub), `README.md`, the licence file                        |

## 3. Add the entry

The key is the model's name in the app and the name of its folder in the
models directory. An entry for a faster-whisper model:

```json
"large-swedish": {
    "display_name": "large-swedish",
    "group": "Language Specific",
    "info": "Optimized for Swedish transcription.",
    "repo_id": "aTrain-core/KB-WhisperSwedish",
    "revision": "824bf78765b22c7e999ea3ec91629c7169f69bcf",
    "license": "Apache-2.0",
    "backend": "faster-whisper",
    "type": "regular",
    "languages": ["sv"]
}
```

| Field                                   | Required              | Used for                                                                                     |
| --------------------------------------- | --------------------- | -------------------------------------------------------------------------------------------- |
| `repo_id`                               | yes                   | download source under `aTrain-core/`; official `Qwen/` repositories for the Qwen3 exception |
| `revision`                              | yes                   | the commit to download; a commit hash, never a branch                                        |
| `license`                               | yes                   | the SBOM; see step 5                                                                         |
| `backend`                               | yes                   | `faster-whisper`, `crisper-transformers`, `qwen3-transformers`, `qwen3-aligner` or `pyannote` |
| `type`                                  | faster-whisper models | `regular`, or `distil` for distilled models (changes decoding settings)                      |
| `languages`                             | no                    | language codes from `aTrain_core/data/languages.json`; without it, all languages are offered |
| `group`                                 | no                    | section on the Models page: `Recommended`, `Language Specific` or `All others` (default)     |
| `display_name`                          | no                    | name on the Models page, defaults to the key                                                 |
| `info`                                  | no                    | tooltip on the Models page                                                                   |
| `dependencies`                          | no                    | model keys downloaded and verified before this one, such as a shared aligner |
| `files`, `repo_size`, `repo_size_human` | yes                   | written by the script in step 4                                                              |

## 4. Pin hashes and sizes

```bash
uv run scripts/refresh_model_hashes.py <key>          # writes files and sizes
uv run scripts/refresh_model_hashes.py --check <key>  # compares, exit 1 on drift
```

The script reads the file list of the pinned revision, so a change of
`revision` needs a new run. The resulting diff of `models.json` is checked,
like a lockfile.

## 5. Licence and SBOM

The release SBOM lists every model with its licence, and
`.github/scripts/build-sbom.py` refuses a models.json entry without one. Use an
[SPDX identifier](https://spdx.org/licenses/) where one exists, otherwise
`LicenseRef-<Owner>-<Name>` as for `crisperwhisper-v2-large`.

A model whose terms users have to accept before downloading needs code: the
licence dialog on the Models page is wired to `crisperwhisper-v2-large` in
`aTrain/pages/models.py`.

## 6. Check

- The unit tests pass (`uv pip install pytest`, then
  `uv run --no-sync python -m pytest tests/unit`); they fail for an entry
  without pinned hashes.
- In the app, the model appears on the Models page in its group, downloads,
  and transcribes a recording in its target language.
- The pull request's CI builds the SBOM with the new entry.

## Qwen3 ASR

`qwen3-asr-0.6b` and `qwen3-asr-1.7b` run on native Transformers and share
`qwen3-forced-aligner-0.6b` for word timestamps. `get_model` downloads the
aligner as a dependency; its `type: "alignment"` keeps it out of the
transcription selector. Only the languages the aligner supports are offered.

Run the real CPU checks with
`ATRAIN_TEST_QWEN=1 uv run --no-sync pytest tests/core/test_qwen3_transformers_e2e.py -v`.

## Required models

`large-v3-turbo` and `speaker-detection` are required models: builds with
bundled models ship them inside the installer. They come from archives in
aTrain-core datasets, referenced with their sha256 in
`.github/workflows/release.yml` and in the Flatpak manifest in the
[Flathub repository](https://github.com/flathub/io.github.juergenfleiss.aTrain).
Changing a required model means updating those as well.

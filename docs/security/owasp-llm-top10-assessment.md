# OWASP Top 10 for LLM Applications — Applicability Assessment

## About this document

This document evaluates aTrain against the [OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/). aTrain uses OpenAI's [Whisper](https://github.com/openai/whisper) model via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for automatic speech recognition (ASR) and [pyannote.audio](https://github.com/pyannote/pyannote-audio) for speaker diarization. These are **task-specific ML models, not large language models** in the interactive or generative sense. Many of the OWASP LLM risks either do not apply or apply differently in this context.

For each risk, this document states whether it applies to aTrain, provides a conclusion, and gives a detailed assessment with justification.

## Summary

| # | Risk | Applicability | Risk Level |
|---|------|----------|------------|
| [LLM01](#llm01-prompt-injection) | Prompt Injection | Does not apply | N/A |
| [LLM02](#llm02-sensitive-information-disclosure) | Sensitive Information Disclosure | Partially applies — low risk | Low |
| [LLM03](#llm03-supply-chain-vulnerabilities) | Supply Chain Vulnerabilities | **Applies** | Medium |
| [LLM04](#llm04-data-and-model-poisoning) | Data and Model Poisoning | Limited applicability — low risk | Low |
| [LLM05](#llm05-improper-output-handling) | Improper Output Handling | Partially applies — low risk | Low |
| [LLM06](#llm06-excessive-agency) | Excessive Agency | Does not apply | N/A |
| [LLM07](#llm07-system-prompt-leakage) | System Prompt Leakage | Does not apply | N/A |
| [LLM08](#llm08-vector-and-embedding-weaknesses) | Vector and Embedding Weaknesses | Does not apply | N/A |
| [LLM09](#llm09-misinformation) | Misinformation | Partially applies | Medium |
| [LLM10](#llm10-unbounded-consumption) | Unbounded Consumption | Partially applies — low risk | Low |

**Key finding:** The majority of OWASP LLM Top 10 risks do not apply or have low relevance to aTrain because Whisper is a task-specific ASR model, not an interactive LLM. The most relevant risk is **LLM03 (Supply Chain Vulnerabilities)**, where improvements to dependency and model integrity verification are recommended.

---

## LLM01: Prompt Injection

**Applicability:** Does not apply

**Conclusion:** Whisper's prompt mechanism is a transcription hint, not an instruction-following interface. Adversarial audio could produce unexpected transcript content but cannot influence application behavior.

**Assessment:**

Prompt injection targets LLMs that accept natural language instructions and can be manipulated into deviating from intended behavior. Whisper is an ASR model — it converts audio to text. It does not accept or follow textual instructions at inference time.

aTrain does expose an optional `initial_prompt` parameter ([`aTrain/components/settings/advanced.py`](../../aTrain/components/settings/advanced.py)) that is passed to Whisper as a conditioning prompt to improve transcription style. This parameter influences transcription formatting (e.g., punctuation, spelling) but **cannot cause the model to execute actions, access data, or change application behavior**. The prompt is set by the user themselves, not by external parties.

A separate attack vector exists where an audio file could contain embedded speech (audible or inaudible) crafted to produce specific text in the transcript — for example, hidden voice commands or misleading content. However, even if such audio were transcribed, the resulting text is **only written to a local file and displayed in the UI**. It is not interpreted as instructions, not passed to another model, and not executed by the application. The impact is limited to the transcript containing unexpected text, which a human reviewer would encounter during review.

---

## LLM02: Sensitive Information Disclosure

**Applicability:** Partially applies — low risk

**Conclusion:** The model itself does not disclose sensitive information. Data handling practices around stored transcriptions should follow the deploying organization's data protection policies.

**Assessment:**

This risk concerns models leaking sensitive data from their training data. Whisper was trained by OpenAI on a large corpus of internet audio. aTrain uses pre-trained model weights from [Hugging Face](https://huggingface.co/Systran) and **does not fine-tune or retrain** models on user data.

- Whisper's output is a transcript of the **input audio only** — it does not generate text from its training data
- User audio files and transcriptions are stored locally on the user's machine ([`aTrain_core.globals.TRANSCRIPT_DIR`](https://github.com/JuergenFleiss/atrain_core))
- No data is transmitted to external servers — the application operates fully offline after model download
- Transcription results are stored as plaintext files on the local filesystem

Transcriptions of sensitive recordings (e.g., medical interviews, legal proceedings) are stored unencrypted on disk. This is a data-at-rest concern, not a model leakage issue.

---

## LLM03: Supply Chain Vulnerabilities

**Applicability:** Applies

**Conclusion:** Supply chain hardening should be improved. Dependency and model integrity verification are the primary gaps. See the [security assessment tracking issue](https://github.com/JuergenFleiss/aTrain/issues/138) for recommendations.

**Assessment:**

aTrain depends on external components that could introduce supply chain risk:

- **ML Models:** Whisper and pyannote models are downloaded from [Hugging Face Hub](https://huggingface.co) at first run via `aTrain_core.load_resources.get_model()` ([`aTrain/utils/models.py:87`](../../aTrain/utils/models.py#L87)). Downloads use HTTPS.
- **Python dependencies:** Pinned to specific versions in [`pyproject.toml`](../../pyproject.toml) (e.g., `nicegui==2.21.1`, `pywebview==6.1`).
- **Core transcription library:** [`aTrain_core`](https://github.com/JuergenFleiss/atrain_core) is pinned to a git tag (`v1.4.1`).

Current mitigations:
- All dependency versions are pinned
- Model downloads use HTTPS (encrypted transport)
- `aTrain_core` is pinned to a specific release tag
- Every release publishes a CycloneDX 1.6 SBOM covering the installed dependencies and the ML models, attached to the GitHub release and the Zenodo record
- `pip-audit` checks the locked dependencies against the PyPI advisory database on every pull request

Gaps:
- No hash/checksum verification for downloaded models
- Git tag pinning does not guarantee integrity — tags are mutable and can be re-pointed in the upstream repository. Commit-SHA pinning would provide a stronger guarantee; tracked as a follow-up.

---

## LLM04: Data and Model Poisoning

**Applicability:** Limited applicability — low risk

**Conclusion:** Risk is present at the supply chain level, not at the application level. aTrain does not train or modify models.

**Assessment:**

This risk concerns attackers manipulating training data or model weights to alter model behavior. aTrain uses **pre-trained, publicly available models** and does not train or fine-tune models.

- Whisper models are published by [Systran](https://huggingface.co/Systran) (faster-whisper) and [OpenAI](https://huggingface.co/openai)
- pyannote models are published by the [pyannote project](https://huggingface.co/pyannote)
- aTrain does not modify model weights
- Users can currently not add custom models. If this feature is introduced in the future (https://github.com/JuergenFleiss/aTrain/issues/72), this point needs to be revisited.

If a model source (Hugging Face repository) were compromised, users could download tampered weights. This is mitigated by using well-known repositories with established trust, but no cryptographic verification is performed (see LLM03).

---

## LLM05: Improper Output Handling

**Applicability:** Partially applies — low risk

**Conclusion:** Transcript output is rendered safely in the UI and stored as plaintext files. There is no execution path where transcript content could cause injection.

**Assessment:**

This risk concerns applications that process LLM output without validation, enabling injection attacks (XSS, SQL injection, etc.).

- Whisper produces a text transcript of the input audio
- The transcript is written to local files (plaintext, SRT, VTT, etc.) via `aTrain_core`
- Transcripts are displayed in the UI via NiceGUI's `ui.label()` component, which **escapes HTML by default**
- Transcripts are **not used as input to other systems** (no database queries, no command execution, no API calls)

---

## LLM06: Excessive Agency

**Applicability:** Does not apply

**Conclusion:** aTrain is a single-purpose transcription tool with no agent behavior.

**Assessment:**

This risk concerns LLM-based agents that autonomously perform actions (API calls, database writes, system commands) beyond what is intended.

- Whisper produces text output only — it cannot trigger actions
- The application does not chain model outputs into further processing steps
- No tool use, function calling, or autonomous decision-making

---

## LLM07: System Prompt Leakage

**Applicability:** Does not apply

**Conclusion:** aTrain does not use system prompts. No sensitive configuration or business logic is exposed through prompt mechanisms.

**Assessment:**

This risk concerns attackers extracting system prompts that contain sensitive instructions or business logic.

aTrain does not use system prompts. The optional `initial_prompt` parameter is a user-provided transcription hint (e.g., preferred spelling of names) — it contains no sensitive configuration, secrets, or business logic.

---

## LLM08: Vector and Embedding Weaknesses

**Applicability:** Does not apply

**Conclusion:** aTrain does not use embeddings or vector storage.

**Assessment:**

This risk concerns vulnerabilities in vector databases and embedding stores used for Retrieval-Augmented Generation (RAG). aTrain does not use vector databases, embedding stores, RAG pipelines, or semantic search.

---

## LLM09: Misinformation

**Applicability:** Partially applies

**Conclusion:** Transcription inaccuracy is an inherent property of ASR models. Users should be aware that transcripts require human review, especially for official or legal purposes.

**Assessment:**

This risk concerns models generating factually incorrect or misleading content. In aTrain's context, this translates to **transcription accuracy** — Whisper may produce incorrect transcriptions (wrong words, hallucinated text, missed segments).

- Whisper is a state-of-the-art ASR model but is not perfect — word error rates vary by language, audio quality, and domain
- Whisper is known to occasionally [hallucinate text](https://arxiv.org/abs/2401.01021) on silent or low-quality audio segments
- aTrain provides multiple model sizes (tiny through large-v3) — larger models generally produce more accurate results

Current mitigations:
- Users select the model size themselves, with larger models recommended for important work
- Original audio is preserved alongside transcriptions for verification
- Speaker diarization helps users verify who said what
- VAD detection is applied to remove silent segments to reduce hallucination
Gaps:
- No confidence scores displayed to the user
- No explicit warning about potential transcription errors in the UI (tracked in [#143](https://github.com/JuergenFleiss/aTrain/issues/143))

---

## LLM10: Unbounded Consumption

**Applicability:** Partially applies — low risk

**Conclusion:** Low risk for the default desktop deployment. Organizations deploying aTrain as a shared service should implement resource limits at the infrastructure level.

**Assessment:**

This risk concerns excessive resource consumption through model inference.

- aTrain is a **local desktop application** — resource consumption affects only the user's own machine
- There is no multi-user scenario (no shared server, no API)
- Transcription is CPU/GPU intensive — processing time scales with audio length (roughly 3x realtime on mid-range CPUs)
- The file upload limit is set to 10 GB ([`aTrain/utils/transcription.py:18`](../../aTrain/utils/transcription.py#L18))


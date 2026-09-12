import gc
import json
import traceback
from concurrent.futures.process import BrokenProcessPool
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from multiprocessing import Manager, Process
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypedDict, cast

import yaml
from aTrain.components.dialogs.error import dialog_error
from aTrain.components.dialogs.finished import dialog_batch_finished, dialog_finished
from aTrain.components.dialogs.process import close_dialog_process, dialog_process
from aTrain.utils.archive import delete_transcription
from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.settings import (
    ComputeType,
    Device,
    Settings,
    check_inputs_transcribe,
    load_formats,
)
from nicegui import app, events, run, ui
from nicegui.run import SubprocessException
from nicegui.run import setup as setup_process_pool

RAW_TRANSCRIPT_FILENAME = "raw_transcript.json"
DIARIZED_TRANSCRIPT_FILENAME = "diarized_transcript.json"
PHASE1_MANIFEST_FILENAME = "folder_batch_phase1_manifest.json"
PHASE2_MANIFEST_FILENAME = "folder_batch_phase2_manifest.json"
FOLDER_BATCH_RUNNING_KEY = "folder_batch_running"


class State(TypedDict):
    model: str
    language: str
    speaker_detection: bool
    speaker_count: float | None
    GPU: bool
    compute_type: str
    temperature_override: float | None
    initial_prompt: str | None
    cpu_threads: int


class BatchResult(TypedDict):
    output_directory: str
    successful: int
    failed: int
    failures: list[dict[str, str]]


def discover_media_files(folder: Path) -> list[Path]:
    allowed_extensions = {extension.lower() for extension in load_formats()}
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in allowed_extensions
        ),
        key=lambda path: path.name.lower(),
    )


def create_batch_file_id(file_path: Path, model: str, output_root: Path) -> str:
    from werkzeug.utils import secure_filename

    base_name = secure_filename(f"{file_path.stem}_transcript_{model}") or "transcript"
    candidate = base_name
    suffix = 2
    while (output_root / candidate).exists():
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def update_metadata_fields(transcript_dir: Path, file_id: str, **fields: str) -> None:
    metadata_path = transcript_dir / file_id / "metadata.txt"
    with metadata_path.open(encoding="utf-8") as metadata_file:
        metadata = yaml.safe_load(metadata_file) or {}
    metadata.update(fields)
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        yaml.dump(metadata, metadata_file)


def write_raw_transcript(transcript_dir: Path, file_id: str, transcript: dict) -> None:
    raw_path = transcript_dir / file_id / RAW_TRANSCRIPT_FILENAME
    with raw_path.open("w", encoding="utf-8") as raw_file:
        json.dump(transcript, raw_file, ensure_ascii=False)


def read_raw_transcript(transcript_dir: Path, file_id: str) -> dict:
    raw_path = transcript_dir / file_id / RAW_TRANSCRIPT_FILENAME
    with raw_path.open(encoding="utf-8") as raw_file:
        return json.load(raw_file)


def write_diarized_transcript(transcript_dir: Path, file_id: str, transcript: dict) -> None:
    diarized_path = transcript_dir / file_id / DIARIZED_TRANSCRIPT_FILENAME
    with diarized_path.open("w", encoding="utf-8") as diarized_file:
        json.dump(transcript, diarized_file, ensure_ascii=False)


def read_diarized_transcript(transcript_dir: Path, file_id: str) -> dict:
    diarized_path = transcript_dir / file_id / DIARIZED_TRANSCRIPT_FILENAME
    with diarized_path.open(encoding="utf-8") as diarized_file:
        return json.load(diarized_file)


def write_phase1_manifest(
    output_root: Path,
    prepared: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> None:
    manifest_path = output_root / PHASE1_MANIFEST_FILENAME
    manifest = {
        "output_directory": str(output_root),
        "prepared": prepared,
        "failures": failures,
    }
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False)


def read_phase1_manifest(output_root: Path) -> dict[str, Any] | None:
    manifest_path = output_root / PHASE1_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    prepared = []
    for item in manifest.get("prepared", []):
        file_id = item.get("file_id")
        if file_id and (output_root / file_id / RAW_TRANSCRIPT_FILENAME).is_file():
            prepared.append(item)
    return {
        "output_directory": str(output_root),
        "prepared": prepared,
        "failures": list(manifest.get("failures", [])),
    }


def write_phase2_manifest(
    output_root: Path,
    completed: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> None:
    manifest_path = output_root / PHASE2_MANIFEST_FILENAME
    manifest = {
        "output_directory": str(output_root),
        "completed": completed,
        "failures": failures,
    }
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False)


def read_phase2_manifest(output_root: Path) -> dict[str, Any] | None:
    manifest_path = output_root / PHASE2_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    completed = []
    for item in manifest.get("completed", []):
        file_id = item.get("file_id")
        if file_id and (output_root / file_id / DIARIZED_TRANSCRIPT_FILENAME).is_file():
            completed.append({**item, "transcript": read_diarized_transcript(output_root, file_id)})
    return {
        "output_directory": str(output_root),
        "completed": completed,
        "failures": list(manifest.get("failures", [])),
    }


def release_model_memory(use_gpu: bool) -> None:
    gc.collect()
    if use_gpu:
        with suppress(Exception):
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def build_settings(
    *,
    state: State,
    file_path: Path,
    file_id: str,
    timestamp: str,
    progress: Any,
) -> Settings:
    return Settings(
        file=file_path,
        file_id=file_id,
        file_name=file_path.name,
        model=state.get("model"),
        language=state.get("language"),
        speaker_detection=state.get("speaker_detection"),
        speaker_count=int(state.get("speaker_count") or 0) or None,
        device=Device.GPU if state.get("GPU") else Device.CPU,
        compute_type=ComputeType(state.get("compute_type")),
        timestamp=timestamp,
        temperature=state.get("temperature_override"),
        initial_prompt=state.get("initial_prompt") or None,
        cpu_threads=int(state.get("cpu_threads", 0)) or 0,
        progress=progress,
    )


def update_batch_progress(
    progress: Any,
    *,
    task: str,
    current: float,
    total: float,
    file_index: int,
    file_total: int,
    file_name: str,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    progress.update(
        {
            "task": task,
            "current": current,
            "total": total,
            "file_index": file_index,
            "file_total": file_total,
            "progress_index": file_index if progress_index is None else progress_index,
            "progress_total": file_total if progress_total is None else progress_total,
            "file_name": file_name,
        }
    )


def preserve_phase1_failure(
    *,
    output_root: Path,
    file_id: str,
    settings: Settings,
    error: str,
) -> None:
    import aTrain_core.outputs as outputs

    outputs.create_directory(file_id)
    outputs.write_logfile(f"Phase 1 transcription failed: {error}", file_id)
    metadata_path = output_root / file_id / "metadata.txt"
    if metadata_path.is_file():
        update_metadata_fields(
            output_root,
            file_id,
            transcription_status="failed",
            diarization_status="pending" if settings.speaker_detection else "skipped",
            output_status="failed",
        )
        return

    metadata = {
        "file_id": settings.file_id,
        "filename": settings.file_name,
        "model": settings.model,
        "language": settings.language,
        "speaker_detection": settings.speaker_detection,
        "num_speakers": settings.speaker_count,
        "device": settings.device.value,
        "compute_type": settings.compute_type.value,
        "timestamp": settings.timestamp,
        "transcription_status": "failed",
        "diarization_status": "pending" if settings.speaker_detection else "skipped",
        "output_status": "failed",
        "error": error,
    }
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        yaml.dump(metadata, metadata_file)


def run_speaker_detection_batch_process(
    *,
    output_root: Path,
    state: State,
    prepared: list[dict[str, Any]],
    progress: Any,
    return_dict: Any,
) -> None:
    import os

    try:
        import aTrain_core.outputs as outputs
        import torch
        from aTrain_core.globals import SAMPLING_RATE
        from aTrain_core.load_resources import get_model
        from aTrain_core.transcribe import CustomProgressHook, load_audio
        from pyannote.audio import Pipeline

        outputs.TRANSCRIPT_DIR = output_root
        pipeline = Pipeline.from_pretrained(get_model("speaker-detection"))
        if not pipeline:
            raise Exception("Failed to initialize speaker detection pipeline!")
        pipeline.to(torch.device("cuda"))

        completed: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        total_files = len(prepared)
        write_phase2_manifest(output_root, completed, failures)
        for index, item in enumerate(prepared):
            file_path = Path(item["file_path"])
            file_id = item["file_id"]
            settings = build_settings(
                state=state,
                file_path=file_path,
                file_id=file_id,
                timestamp=item["timestamp"],
                progress=progress,
            )
            progress_index = index + total_files
            update_batch_progress(
                progress,
                task="Detect Speakers",
                current=0,
                total=1,
                file_index=index,
                file_total=total_files,
                progress_index=progress_index,
                progress_total=total_files * 2,
                file_name=f"Diarize: {file_path.name}",
            )
            try:
                transcript = read_raw_transcript(output_root, file_id)
                update_metadata_fields(output_root, file_id, diarization_status="running")
                audio_array, _audio_duration = load_audio(settings)
                audio = {
                    "waveform": torch.from_numpy(audio_array[None, :]),
                    "sample_rate": SAMPLING_RATE,
                }
                outputs.write_logfile(
                    "Speaker detection model already loaded for folder batch", file_id
                )
                outputs.write_logfile("Detecting speakers", file_id)
                with CustomProgressHook(settings.progress) as hook:
                    output = pipeline(audio, num_speakers=settings.speaker_count, hook=hook)
                speaker_results = outputs.transform_speakers_results(output.speaker_diarization)
                outputs.write_logfile("Transformed diarization segments", file_id)
                transcript = outputs.assign_word_speakers(speaker_results, transcript)
                outputs.write_logfile("Assigned speakers to words", file_id)
                write_diarized_transcript(output_root, file_id, transcript)
                completed_item = {
                    "file_path": str(file_path),
                    "file_id": file_id,
                    "timestamp": item["timestamp"],
                }
                completed.append(completed_item)
                write_phase2_manifest(output_root, completed, failures)
                update_metadata_fields(output_root, file_id, diarization_status="complete")
                del audio_array, audio, transcript, speaker_results
            except Exception as exc:
                update_metadata_fields(output_root, file_id, diarization_status="failed")
                update_metadata_fields(output_root, file_id, output_status="failed")
                failures.append({"file": file_path.name, "file_id": file_id, "error": str(exc)})
                write_phase2_manifest(output_root, completed, failures)

        return_dict["transcripts"] = [
            {
                **item,
                "transcript": read_diarized_transcript(output_root, item["file_id"]),
            }
            for item in completed
        ]
        return_dict["failures"] = failures
    except Exception as exc:
        return_dict["error"] = str(exc)
        return_dict["traceback"] = traceback.format_exc()
    finally:
        release_model_memory(True)
    os._exit(0)


def run_speaker_detection_batch_in_process(
    *,
    output_root: Path,
    state: State,
    prepared: list[dict[str, Any]],
    progress: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    with Manager() as manager:
        return_dict = manager.dict()
        process = Process(
            target=run_speaker_detection_batch_process,
            kwargs={
                "output_root": output_root,
                "state": state,
                "prepared": prepared,
                "progress": progress,
                "return_dict": return_dict,
            },
            daemon=True,
        )
        process.start()
        process.join()
        exit_code = process.exitcode
        process.close()
        recovered = read_phase2_manifest(output_root)
        if "error" in return_dict:
            if recovered and recovered["completed"]:
                recovered["failures"].append(
                    {
                        "file": "folder batch",
                        "error": "Recovered completed diarized transcripts after "
                        f"phase 2 process error: {return_dict['error']}",
                    }
                )
                return list(recovered["completed"]), list(recovered["failures"])
            raise RuntimeError(return_dict["error"])
        if "transcripts" not in return_dict:
            if recovered and recovered["completed"]:
                recovered["failures"].append(
                    {
                        "file": "folder batch",
                        "error": "Recovered completed diarized transcripts after "
                        f"phase 2 process exit code {exit_code}",
                    }
                )
                return list(recovered["completed"]), list(recovered["failures"])
            raise RuntimeError(
                f"Speaker detection batch process exited unexpectedly with code {exit_code}"
            )
        return list(return_dict["transcripts"]), list(return_dict.get("failures", []))


def transcribe_folder_batch(folder: Path, state: State, progress: Any) -> BatchResult:
    if state.get("GPU"):
        return transcribe_folder_batch_gpu(folder, state, progress)
    return transcribe_folder_batch_impl(folder, state, progress)


def transcribe_folder_batch_phase1_process(
    folder: Path,
    state: State,
    progress: Any,
    return_dict: Any,
) -> None:
    import os

    try:
        import aTrain_core.outputs as outputs

        output_root = folder / "transcriptions"
        outputs.TRANSCRIPT_DIR = output_root
        transcribe_folder_batch_phase1(
            folder, state, progress, output_root, return_dict=return_dict
        )
    except Exception as exc:
        return_dict["error"] = str(exc)
        return_dict["traceback"] = traceback.format_exc()
    os._exit(0)


def transcribe_folder_batch_gpu(folder: Path, state: State, progress: Any) -> BatchResult:
    """Run Whisper phase in a short-lived process, then diarize after it exits."""
    output_root = folder / "transcriptions"
    with Manager() as manager:
        return_dict = manager.dict()
        process = Process(
            target=transcribe_folder_batch_phase1_process,
            kwargs={
                "folder": folder,
                "state": state,
                "progress": progress,
                "return_dict": return_dict,
            },
            daemon=True,
        )
        process.start()
        process.join()
        exit_code = process.exitcode
        process.close()
        if "error" in return_dict:
            raise RuntimeError(return_dict["error"])
        if "result" in return_dict:
            result = dict(return_dict["result"])
        else:
            result = read_phase1_manifest(output_root)
            if result is None or not result["prepared"]:
                raise RuntimeError(
                    f"Folder transcription process exited unexpectedly with code {exit_code}"
                )
            result["failures"].append(
                {
                    "file": "folder batch",
                    "error": "Recovered completed raw transcripts after "
                    f"phase 1 process exit code {exit_code}",
                }
            )
    return complete_folder_batch_outputs(
        output_root=Path(result["output_directory"]),
        state=state,
        progress=progress,
        prepared=list(result["prepared"]),
        failures=list(result["failures"]),
    )


def transcribe_folder_batch_phase1(
    folder: Path,
    state: State,
    progress: Any,
    output_root: Path,
    return_dict: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    # Lazy imports keep the app startup path light and make this worker self-contained.
    import aTrain_core.outputs as outputs
    from aTrain_core.load_resources import get_model, load_model_config_file
    from aTrain_core.transcribe import load_audio, transcription_with_progress_bar
    from faster_whisper import WhisperModel

    files = discover_media_files(folder)
    model = state.get("model")
    model_path = get_model(model)
    model_type = load_model_config_file()[model]["type"]
    output_root.mkdir(parents=True, exist_ok=True)

    failures: list[dict[str, str]] = []
    prepared: list[dict[str, Any]] = []
    whisper_model: Any | None = None
    try:
        write_phase1_manifest(output_root, prepared, failures)
        whisper_model = WhisperModel(
            model_size_or_path=model_path.as_posix(),
            device="cuda" if state.get("GPU") else "cpu",
            compute_type=state.get("compute_type"),
            cpu_threads=int(state.get("cpu_threads", 0)) or 0,
        )
        for index, file_path in enumerate(files):
            timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
            file_id = create_batch_file_id(file_path, model, output_root)
            update_batch_progress(
                progress,
                task="Prepare",
                current=0,
                total=1,
                file_index=index,
                file_total=len(files),
                progress_index=index,
                progress_total=len(files) * 2 if state.get("speaker_detection") else len(files),
                file_name=f"Transcribe: {file_path.name}",
            )
            settings = build_settings(
                state=state,
                file_path=file_path,
                file_id=file_id,
                timestamp=timestamp,
                progress=progress,
            )
            try:
                check_inputs_transcribe(
                    settings.file_name,
                    settings.model,
                    settings.language,
                    settings.device,
                )
                outputs.create_directory(file_id)
                outputs.write_logfile(f"File ID created: {file_id}", file_id)
                audio_array, audio_duration = load_audio(settings)
                outputs.create_metadata(settings, audio_duration)
                update_metadata_fields(
                    output_root,
                    file_id,
                    transcription_status="running",
                    diarization_status="pending" if settings.speaker_detection else "skipped",
                    output_status="pending",
                )
                outputs.write_logfile("Model already loaded for folder batch", file_id)
                segments, info = whisper_model.transcribe(
                    audio=audio_array,
                    vad_filter=True,
                    beam_size=5,
                    word_timestamps=True,
                    language=None if settings.language == "auto-detect" else settings.language,
                    max_new_tokens=None if model_type == "distil" else 128,
                    no_speech_threshold=0.6,
                    condition_on_previous_text=model_type != "distil",
                    initial_prompt=settings.initial_prompt,
                    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
                    if settings.temperature is None
                    else settings.temperature,
                )
                segments = transcription_with_progress_bar(segments, info, settings.progress)
                transcript = {"segments": [outputs.named_tuple_to_dict(s) for s in segments]}
                write_raw_transcript(output_root, file_id, transcript)
                update_metadata_fields(
                    output_root,
                    file_id,
                    transcription_status="complete",
                )
                outputs.write_logfile("Transcription successful", file_id)
                prepared.append(
                    {
                        "file_path": str(file_path),
                        "file_id": file_id,
                        "timestamp": timestamp,
                    }
                )
                write_phase1_manifest(output_root, prepared, failures)
            except Exception as exc:
                preserve_phase1_failure(
                    output_root=output_root,
                    file_id=file_id,
                    settings=settings,
                    error=str(exc),
                )
                failures.append({"file": file_path.name, "error": str(exc)})
                write_phase1_manifest(output_root, prepared, failures)
        if return_dict is not None:
            import os

            return_dict["result"] = {
                "output_directory": str(output_root),
                "prepared": prepared,
                "failures": failures,
            }
            os._exit(0)
        return prepared, failures
    finally:
        if whisper_model is not None:
            del whisper_model
        release_model_memory(state.get("GPU"))


def complete_folder_batch_outputs(
    *,
    output_root: Path,
    state: State,
    progress: Any,
    prepared: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> BatchResult:
    import aTrain_core.outputs as outputs
    from aTrain_core.transcribe import load_audio, run_speaker_detection

    original_transcript_dir = outputs.TRANSCRIPT_DIR
    outputs.TRANSCRIPT_DIR = output_root
    successful = 0
    try:
        total_files = len(prepared)
        if state.get("GPU") and state.get("speaker_detection") and prepared:
            items_to_write, diarization_failures = run_speaker_detection_batch_in_process(
                output_root=output_root,
                state=state,
                prepared=prepared,
                progress=progress,
            )
            failures.extend(diarization_failures)
        else:
            items_to_write = prepared

        for index, item in enumerate(items_to_write):
            file_path = Path(item["file_path"])
            file_id = item["file_id"]
            settings = build_settings(
                state=state,
                file_path=file_path,
                file_id=file_id,
                timestamp=item["timestamp"],
                progress=progress,
            )
            progress_index = index + (total_files if settings.speaker_detection else 0)
            update_batch_progress(
                progress,
                task="Detect Speakers" if settings.speaker_detection else "Prepare",
                current=0,
                total=1,
                file_index=index,
                file_total=total_files,
                progress_index=progress_index,
                progress_total=total_files * 2 if settings.speaker_detection else total_files,
                file_name=f"Diarize: {file_path.name}"
                if settings.speaker_detection
                else f"Write: {file_path.name}",
            )
            diarization_complete = False
            try:
                transcript = item.get("transcript") or read_raw_transcript(output_root, file_id)
                diarization_complete = "transcript" in item
                if settings.speaker_detection and transcript and "transcript" not in item:
                    update_metadata_fields(output_root, file_id, diarization_status="running")
                    audio_array, audio_duration = load_audio(settings)
                    transcript = run_speaker_detection(
                        settings, audio_duration, audio_array, transcript
                    )
                    del audio_array
                    diarization_complete = True
                    update_metadata_fields(output_root, file_id, diarization_status="complete")
                outputs.create_output_files(
                    transcript, settings.speaker_detection, settings.file_id
                )
                update_metadata_fields(output_root, file_id, output_status="complete")
                outputs.add_processing_time_to_metadata(settings.file_id)
                outputs.write_logfile("Processing time added to metadata", file_id)
                successful += 1
            except Exception as exc:
                update_metadata_fields(output_root, file_id, output_status="failed")
                if settings.speaker_detection and not diarization_complete:
                    update_metadata_fields(output_root, file_id, diarization_status="failed")
                failures.append({"file": file_path.name, "error": str(exc)})
        update_batch_progress(
            progress,
            task="Prepare",
            current=1,
            total=1,
            file_index=max(total_files - 1, 0),
            file_total=total_files,
            progress_index=max(
                (total_files * 2 if state.get("speaker_detection") else total_files) - 1,
                0,
            ),
            progress_total=total_files * 2 if state.get("speaker_detection") else total_files,
            file_name="Complete",
        )
        return {
            "output_directory": str(output_root),
            "successful": successful,
            "failed": len(failures),
            "failures": failures,
        }
    finally:
        outputs.TRANSCRIPT_DIR = original_transcript_dir
        release_model_memory(state.get("GPU"))


def transcribe_folder_batch_impl(folder: Path, state: State, progress: Any) -> BatchResult:
    import aTrain_core.outputs as outputs

    output_root = folder / "transcriptions"
    original_transcript_dir = outputs.TRANSCRIPT_DIR
    outputs.TRANSCRIPT_DIR = output_root
    try:
        prepared, failures = transcribe_folder_batch_phase1(folder, state, progress, output_root)
        return complete_folder_batch_outputs(
            output_root=output_root,
            state=state,
            progress=progress,
            prepared=prepared,
            failures=failures,
        )
    finally:
        outputs.TRANSCRIPT_DIR = original_transcript_dir


@dataclass(slots=True)
class UploadPayload:
    """Platform-neutral description of the file to transcribe.

    Two callers feed the same pipeline: the browser upload on Windows/macOS
    (a NiceGUI `UploadEventArguments`) and the native file picker on
    Linux/Flatpak (a path on disk). Normalising both into this type keeps
    NiceGUI's event class out of the transcription code, so an upload-API
    change like 2.x `.name`/`.content` -> 3.x `.file` can only ever break the
    one adapter below instead of silently breaking one of the two platforms.
    """

    name: str
    upload: ui.upload.FileUpload | None = None
    path: Path | None = None

    async def materialise(self, directory: Path, filename: str) -> Path:
        """Return a path the engine can read, staging the upload if needed."""
        if self.path is not None:
            return self.path  # already on disk - no copy, the picker gave us a real file
        if self.upload is None:
            raise ValueError(f"No file to transcribe: {self.name!r} has neither upload nor path")
        target = directory / filename
        await self.upload.save(target)
        return target


async def start_transcription(file: events.UploadEventArguments):
    """NiceGUI `on_upload` handler (browser upload path)."""
    await run_pipeline(UploadPayload(name=file.file.name, upload=file.file))


async def start_transcription_from_path(path: Path, name: str):
    """Entry point for the native file picker (Linux/Flatpak path)."""
    await run_pipeline(UploadPayload(name=name, path=path))


async def run_pipeline(payload: UploadPayload):
    # Lazy import for improved startup speed
    from aTrain_core.transcribe import prepare_transcription, transcribe

    file_id: str | None = None
    with Manager() as manager, TemporaryDirectory() as tmp_dir:
        progress = manager.dict({"task": "Prepare", "current": 0, "total": 999999})
        dialog_process(progress)
        # Snapshot rather than read live: the page re-renders while the upload is
        # staged, and `get_model_options` resets `model` to None whenever no model
        # is on disk yet. Reading through to the live storage would also let a user
        # switching the model mid-upload retarget a run that is already under way.
        state = cast(State, dict(app.storage.general))
        try:
            device = Device.GPU if state.get("GPU") else Device.CPU
            # Validate first: it needs nothing but the name and the settings, and
            # rejecting a wrong model or language should not cost a directory and
            # a full copy of the upload beforehand.
            check_inputs_transcribe(payload.name, state.get("model"), state.get("language"), device)
            safe_file, file_id, timestamp = prepare_transcription(Path(payload.name))
            source = await payload.materialise(Path(tmp_dir), safe_file.name)
            settings = Settings(
                file=source,
                file_id=file_id,
                file_name=payload.name,
                model=state.get("model"),
                language=state.get("language"),
                speaker_detection=state.get("speaker_detection"),
                speaker_count=int(state.get("speaker_count") or 0) or None,
                device=device,
                compute_type=ComputeType(state.get("compute_type")),
                timestamp=timestamp,
                temperature=state.get("temperature_override"),
                initial_prompt=state.get("initial_prompt") or None,
                cpu_threads=int(state.get("cpu_threads", 0)) or 0,
                progress=progress,
            )
            await run.cpu_bound(transcribe, settings=settings)
            close_dialog_process()
            dialog_finished(file_id)

        except BrokenProcessPool:
            if file_id is not None:
                delete_transcription(file_id)
            setup_process_pool()
            close_dialog_process()
            ui.navigate.reload()

        except SubprocessException as e:
            close_dialog_process()
            dialog_error(error=e.original_message, traceback=e.original_traceback)

        except Exception as e:
            close_dialog_process()
            dialog_error(error=str(e), traceback=traceback.format_exc())


async def start_folder_transcription(folder: Path):
    if app.storage.general.get(FOLDER_BATCH_RUNNING_KEY):
        ui.notify("A folder transcription is already running", color="warning")
        return
    folder = Path(folder)
    if not folder.is_dir():
        ui.notify("Please select a valid folder", color="negative")
        return
    files = discover_media_files(folder)
    if not files:
        ui.notify("No supported media files found in this folder", color="warning")
        return

    app.storage.general[FOLDER_BATCH_RUNNING_KEY] = True
    with Manager() as manager:
        progress = manager.dict(
            {
                "task": "Prepare",
                "current": 0,
                "total": 1,
                "file_index": 0,
                "file_total": len(files),
                "progress_index": 0,
                "progress_total": len(files) * 2
                if app.storage.general.get("speaker_detection")
                else len(files),
                "file_name": files[0].name,
            }
        )
        dialog_process(progress)
        state = cast(State, dict(app.storage.general))
        try:
            result = await run.cpu_bound(
                transcribe_folder_batch,
                folder=folder,
                state=state,
                progress=progress,
            )
            close_dialog_process()
            dialog_batch_finished(
                Path(result["output_directory"]),
                result["successful"],
                result["failed"],
            )
            if result["failed"]:
                ui.notify(
                    f"{result['failed']} file(s) failed. Completed the rest.",
                    color="warning",
                )

        except BrokenProcessPool:
            setup_process_pool()
            close_dialog_process()
            ui.navigate.reload()

        except SubprocessException as e:
            close_dialog_process()
            dialog_error(error=e.original_message, traceback=e.original_traceback)

        except Exception as e:
            close_dialog_process()
            dialog_error(error=str(e), traceback=traceback.format_exc())
        finally:
            app.storage.general[FOLDER_BATCH_RUNNING_KEY] = False

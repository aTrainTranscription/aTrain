import json
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace

import yaml


class Device(StrEnum):
    CPU = "cpu"
    GPU = "gpu"


class ComputeType(StrEnum):
    INT8 = "int8"
    FLOAT16 = "float16"
    FLOAT32 = "float32"


@dataclass
class Settings:
    file: Path
    file_id: str
    file_name: str
    model: str
    language: str
    speaker_detection: bool
    speaker_count: int | None
    device: Device
    compute_type: ComputeType
    timestamp: str
    temperature: float | None
    initial_prompt: str | None = None
    progress: dict = field(default_factory=dict)
    cpu_threads: int = 0


def _install_lightweight_runtime_stubs() -> None:
    nicegui = types.ModuleType("nicegui")
    nicegui.app = SimpleNamespace(storage=SimpleNamespace(general={}))
    nicegui.events = SimpleNamespace(UploadEventArguments=object)
    nicegui.run = SimpleNamespace(cpu_bound=lambda func, **kwargs: func(**kwargs))
    nicegui.ui = SimpleNamespace(
        notify=lambda *args, **kwargs: None,
        navigate=SimpleNamespace(reload=lambda: None),
        timer=object,
        dialog=object,
        upload=SimpleNamespace(FileUpload=object),
    )
    nicegui.ElementFilter = lambda *args, **kwargs: []
    sys.modules.setdefault("nicegui", nicegui)

    nicegui_run = types.ModuleType("nicegui.run")

    class SubprocessException(Exception):  # noqa: N818 - mirrors NiceGUI's public name
        original_message = ""
        original_traceback = ""

    nicegui_run.SubprocessException = SubprocessException
    nicegui_run.setup = lambda: None
    nicegui_run.tear_down = lambda: None
    sys.modules.setdefault("nicegui.run", nicegui_run)

    outputs = types.ModuleType("aTrain_core.outputs")
    outputs.TRANSCRIPT_DIR = Path("transcriptions")

    def output_dir(file_id: str) -> Path:
        return Path(outputs.TRANSCRIPT_DIR) / file_id

    def create_directory(file_id: str) -> None:
        output_dir(file_id).mkdir(parents=True, exist_ok=True)

    def write_logfile(message: str, file_id: str) -> None:
        create_directory(file_id)
        with (output_dir(file_id) / "log.txt").open("a", encoding="utf-8") as log_file:
            log_file.write(f"{message}\n")

    def create_metadata(settings_obj: Settings, audio_duration: int) -> None:
        create_directory(settings_obj.file_id)
        metadata = {
            "audio_duration": audio_duration,
            "compute_type": settings_obj.compute_type.value,
            "device": settings_obj.device.value,
            "file_id": settings_obj.file_id,
            "filename": settings_obj.file_name,
            "language": settings_obj.language,
            "model": settings_obj.model,
            "num_speakers": settings_obj.speaker_count,
            "speaker_detection": settings_obj.speaker_detection,
            "timestamp": settings_obj.timestamp,
        }
        with (output_dir(settings_obj.file_id) / "metadata.txt").open(
            "w", encoding="utf-8"
        ) as metadata_file:
            yaml.dump(metadata, metadata_file)

    def create_output_files(transcript: dict, _speaker_detection: bool, file_id: str) -> None:
        create_directory(file_id)
        with (output_dir(file_id) / "transcription.json").open(
            "w", encoding="utf-8"
        ) as output_file:
            json.dump(transcript, output_file)

    def named_tuple_to_dict(segment):
        if isinstance(segment, dict):
            return dict(segment)
        if hasattr(segment, "_asdict"):
            return segment._asdict()
        return dict(vars(segment))

    outputs.add_processing_time_to_metadata = lambda file_id: None
    outputs.assign_word_speakers = lambda _speakers, transcript: transcript
    outputs.create_directory = create_directory
    outputs.create_metadata = create_metadata
    outputs.create_output_files = create_output_files
    outputs.named_tuple_to_dict = named_tuple_to_dict
    outputs.transform_speakers_results = lambda segments: segments
    outputs.write_logfile = write_logfile
    sys.modules.setdefault("aTrain_core.outputs", outputs)

    core_transcribe = types.ModuleType("aTrain_core.transcribe")
    core_transcribe.CustomProgressHook = object
    core_transcribe.load_audio = lambda settings_obj: ([0.0] * 16000, 1)
    core_transcribe.run_speaker_detection = (
        lambda settings_obj, audio_duration, audio_array, transcript: transcript
    )
    core_transcribe.transcription_with_progress_bar = lambda segments, info, progress: segments
    sys.modules.setdefault("aTrain_core.transcribe", core_transcribe)

    faster_whisper = types.ModuleType("faster_whisper")
    faster_whisper.WhisperModel = object
    sys.modules.setdefault("faster_whisper", faster_whisper)

    werkzeug = types.ModuleType("werkzeug")
    werkzeug_utils = types.ModuleType("werkzeug.utils")
    werkzeug_utils.secure_filename = lambda filename: str(filename).replace(" ", "_")
    sys.modules.setdefault("werkzeug", werkzeug)
    sys.modules.setdefault("werkzeug.utils", werkzeug_utils)


_install_lightweight_runtime_stubs()

from aTrain.utils import transcription  # noqa: E402


def test_discover_media_files_filters_top_level_supported_files(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription, "load_formats", lambda: [".mp3", ".wav"])
    (tmp_path / "b.wav").write_text("audio")
    (tmp_path / "a.mp3").write_text("audio")
    (tmp_path / "notes.txt").write_text("skip")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.mp3").write_text("skip")

    files = transcription.discover_media_files(tmp_path)

    assert [path.name for path in files] == ["a.mp3", "b.wav"]


def test_create_batch_file_id_suffixes_existing_output(tmp_path):
    output_root = tmp_path / "transcriptions"
    output_root.mkdir()
    (output_root / "Interview_transcript_tiny").mkdir()
    (output_root / "Interview_transcript_tiny_2").mkdir()

    file_id = transcription.create_batch_file_id(Path("Interview.mp3"), "tiny", output_root)

    assert file_id == "Interview_transcript_tiny_3"


def test_transcribe_folder_batch_loads_model_once_for_multiple_files(tmp_path, monkeypatch):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "one.mp3").write_text("audio")
    (folder / "two.mp3").write_text("audio")
    monkeypatch.setattr(transcription, "load_formats", lambda: [".mp3"])
    monkeypatch.setattr(transcription, "check_inputs_transcribe", lambda *args: True)

    import aTrain_core.load_resources as load_resources
    import aTrain_core.transcribe as core_transcribe
    import faster_whisper

    model_calls = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            model_calls.append(kwargs)

        def transcribe(self, **kwargs):
            return (
                [{"start": 0.0, "end": 1.0, "text": "hello"}],
                SimpleNamespace(duration=1.0),
            )

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(load_resources, "get_model", lambda model: tmp_path)
    monkeypatch.setattr(
        load_resources,
        "load_model_config_file",
        lambda: {"tiny": {"type": "normal"}},
    )
    monkeypatch.setattr(
        core_transcribe,
        "load_audio",
        lambda settings: ([0.0] * 16000, 1),
    )
    monkeypatch.setattr(
        core_transcribe,
        "transcription_with_progress_bar",
        lambda segments, info, progress: segments,
    )

    result = transcription.transcribe_folder_batch(
        folder,
        {
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": False,
            "speaker_count": 0,
            "GPU": False,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        {},
    )

    assert len(model_calls) == 1
    assert result["successful"] == 2
    assert result["failed"] == 0
    assert (folder / "transcriptions" / "one_transcript_tiny").is_dir()
    assert (folder / "transcriptions" / "two_transcript_tiny").is_dir()
    assert (
        folder / "transcriptions" / "one_transcript_tiny" / transcription.RAW_TRANSCRIPT_FILENAME
    ).is_file()


def test_transcribe_folder_batch_releases_model_before_speaker_detection(tmp_path, monkeypatch):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "one.mp3").write_text("audio")
    monkeypatch.setattr(transcription, "load_formats", lambda: [".mp3"])
    monkeypatch.setattr(transcription, "check_inputs_transcribe", lambda *args: True)

    import aTrain_core.load_resources as load_resources
    import aTrain_core.transcribe as core_transcribe
    import faster_whisper

    class FakeWhisperModel:
        live = False

        def __init__(self, **kwargs):
            FakeWhisperModel.live = True

        def __del__(self):
            FakeWhisperModel.live = False

        def transcribe(self, **kwargs):
            return (
                [{"start": 0.0, "end": 1.0, "text": "hello"}],
                SimpleNamespace(duration=1.0),
            )

    def fake_speaker_detection(settings, audio_duration, audio_array, transcript):
        assert FakeWhisperModel.live is False
        transcript["segments"][0]["speaker"] = "SPEAKER_00"
        return transcript

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(load_resources, "get_model", lambda model: tmp_path)
    monkeypatch.setattr(
        load_resources,
        "load_model_config_file",
        lambda: {"tiny": {"type": "normal"}},
    )
    monkeypatch.setattr(
        core_transcribe,
        "load_audio",
        lambda settings: ([0.0] * 16000, 1),
    )
    monkeypatch.setattr(
        core_transcribe,
        "transcription_with_progress_bar",
        lambda segments, info, progress: segments,
    )
    monkeypatch.setattr(
        core_transcribe,
        "run_speaker_detection",
        fake_speaker_detection,
    )

    result = transcription.transcribe_folder_batch(
        folder,
        {
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": True,
            "speaker_count": 0,
            "GPU": False,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        {},
    )

    output_dir = folder / "transcriptions" / "one_transcript_tiny"
    raw = json.loads((output_dir / transcription.RAW_TRANSCRIPT_FILENAME).read_text())
    final = json.loads((output_dir / "transcription.json").read_text())
    metadata = (output_dir / "metadata.txt").read_text()

    assert result["successful"] == 1
    assert result["failed"] == 0
    assert "speaker" not in raw["segments"][0]
    assert final["segments"][0]["speaker"] == "SPEAKER_00"
    assert "transcription_status: complete" in metadata
    assert "diarization_status: complete" in metadata
    assert "output_status: complete" in metadata


def test_gpu_batch_recovers_phase1_manifest_after_child_exit(tmp_path, monkeypatch):
    folder = tmp_path / "batch"
    output_root = folder / "transcriptions"
    raw_dir = output_root / "one_transcript_tiny"
    raw_dir.mkdir(parents=True)
    (raw_dir / transcription.RAW_TRANSCRIPT_FILENAME).write_text(
        json.dumps({"segments": [{"text": "hello"}]}),
        encoding="utf-8",
    )
    transcription.write_phase1_manifest(
        output_root,
        [
            {
                "file_path": str(folder / "one.mp3"),
                "file_id": "one_transcript_tiny",
                "timestamp": "2026-06-09 10:00:00",
            }
        ],
        [],
    )

    class FailedProcess:
        exitcode = -11

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def join(self):
            pass

        def close(self):
            pass

    def fake_complete_folder_batch_outputs(**kwargs):
        assert kwargs["prepared"][0]["file_id"] == "one_transcript_tiny"
        assert "Recovered completed raw transcripts" in kwargs["failures"][0]["error"]
        return {
            "output_directory": str(output_root),
            "successful": 1,
            "failed": len(kwargs["failures"]),
            "failures": kwargs["failures"],
        }

    monkeypatch.setattr(transcription, "Process", FailedProcess)
    monkeypatch.setattr(
        transcription,
        "complete_folder_batch_outputs",
        fake_complete_folder_batch_outputs,
    )

    result = transcription.transcribe_folder_batch_gpu(
        folder,
        {
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": True,
            "speaker_count": 0,
            "GPU": True,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        {},
    )

    assert result["successful"] == 1
    assert result["failed"] == 1


def test_phase1_failure_preserves_output_folder_metadata_and_log(tmp_path, monkeypatch):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "bad.mp3").write_text("audio")
    output_root = folder / "transcriptions"
    monkeypatch.setattr(transcription, "load_formats", lambda: [".mp3"])
    monkeypatch.setattr(transcription, "check_inputs_transcribe", lambda *args: True)

    import aTrain_core.load_resources as load_resources
    import aTrain_core.outputs as outputs
    import aTrain_core.transcribe as core_transcribe
    import faster_whisper

    original_transcript_dir = outputs.TRANSCRIPT_DIR
    outputs.TRANSCRIPT_DIR = output_root

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(load_resources, "get_model", lambda model: tmp_path)
    monkeypatch.setattr(
        load_resources,
        "load_model_config_file",
        lambda: {"tiny": {"type": "normal"}},
    )
    monkeypatch.setattr(
        core_transcribe,
        "load_audio",
        lambda settings: (_ for _ in ()).throw(RuntimeError("decode failed")),
    )

    try:
        prepared, failures = transcription.transcribe_folder_batch_phase1(
            folder,
            {
                "model": "tiny",
                "language": "auto-detect",
                "speaker_detection": True,
                "speaker_count": 0,
                "GPU": False,
                "compute_type": "int8",
                "temperature_override": None,
                "initial_prompt": None,
                "cpu_threads": 0,
            },
            {},
            output_root,
        )
    finally:
        outputs.TRANSCRIPT_DIR = original_transcript_dir

    output_dir = output_root / "bad_transcript_tiny"
    metadata = yaml.safe_load((output_dir / "metadata.txt").read_text())
    log = (output_dir / "log.txt").read_text()
    manifest = json.loads((output_root / transcription.PHASE1_MANIFEST_FILENAME).read_text())

    assert prepared == []
    assert failures == [{"file": "bad.mp3", "error": "decode failed"}]
    assert output_dir.is_dir()
    assert metadata["transcription_status"] == "failed"
    assert metadata["diarization_status"] == "pending"
    assert metadata["output_status"] == "failed"
    assert "Phase 1 transcription failed: decode failed" in log
    assert manifest["failures"] == failures


def test_batch_progress_displays_real_file_count_for_two_phase_units(monkeypatch):
    from aTrain.components.dialogs import process

    state = {"speaker_detection": True}
    monkeypatch.setattr(
        process,
        "app",
        SimpleNamespace(storage=SimpleNamespace(general=state)),
    )

    process.update_progress(
        {
            "task": "Prepare",
            "current": 1,
            "total": 1,
            "file_index": 6,
            "file_total": 7,
            "progress_index": 13,
            "progress_total": 14,
            "file_name": "Complete",
        },
        datetime.now(),
    )

    assert state["task_number"] == "File 7 of 7"
    assert state["task"] == "Stage 1/2: Transcription - Complete"
    assert state["progress"] == 1


def test_batch_progress_displays_clean_speaker_stage(monkeypatch):
    from aTrain.components.dialogs import process

    state = {"speaker_detection": True}
    monkeypatch.setattr(
        process,
        "app",
        SimpleNamespace(storage=SimpleNamespace(general=state)),
    )

    process.update_progress(
        {
            "task": "Detect Speakers",
            "current": 0,
            "total": 1,
            "file_index": 1,
            "file_total": 7,
            "progress_index": 8,
            "progress_total": 14,
            "file_name": "Diarize: sample.wav",
        },
        datetime.now(),
    )

    assert state["task_number"] == "File 2 of 7"
    assert state["task"] == "Stage 2/2: Speaker diarization - sample.wav"


def test_close_dialog_process_ignores_deleted_client(monkeypatch):
    from aTrain.components.dialogs import process

    def deleted_client_filter(*args, **kwargs):
        raise RuntimeError("The client this element belongs to has been deleted.")

    monkeypatch.setattr(process, "ElementFilter", deleted_client_filter)

    process.close_dialog_process()


def test_close_dialog_process_ignores_deleted_parent_slot(monkeypatch):
    from aTrain.components.dialogs import process

    def deleted_parent_filter(*args, **kwargs):
        raise RuntimeError("The parent element this slot belongs to has been deleted.")

    monkeypatch.setattr(process, "ElementFilter", deleted_parent_filter)

    process.close_dialog_process()


def test_gpu_phase2_runs_one_speaker_detection_process_for_batch(tmp_path, monkeypatch):
    output_root = tmp_path / "transcriptions"
    output_root.mkdir()
    prepared = [
        {
            "file_path": str(tmp_path / "one.mp3"),
            "file_id": "one_transcript_tiny",
            "timestamp": "2026-06-09 10-00-00",
        },
        {
            "file_path": str(tmp_path / "two.mp3"),
            "file_id": "two_transcript_tiny",
            "timestamp": "2026-06-09 10-01-00",
        },
    ]
    for item in prepared:
        output_dir = output_root / item["file_id"]
        output_dir.mkdir()
        (output_dir / transcription.RAW_TRANSCRIPT_FILENAME).write_text(
            json.dumps({"segments": [{"start": 0, "end": 1, "text": "hello"}]}),
            encoding="utf-8",
        )
        (output_dir / "metadata.txt").write_text(
            yaml.dump(
                {
                    "timestamp": item["timestamp"],
                    "transcription_status": "complete",
                    "diarization_status": "pending",
                    "output_status": "pending",
                }
            ),
            encoding="utf-8",
        )

    process_calls = []

    def fake_batch_in_process(**kwargs):
        process_calls.append(kwargs["prepared"])
        return (
            [
                {
                    **item,
                    "transcript": {
                        "segments": [
                            {
                                "start": 0,
                                "end": 1,
                                "text": "hello",
                                "speaker": "SPEAKER_00",
                            }
                        ]
                    },
                }
                for item in kwargs["prepared"]
            ],
            [],
        )

    monkeypatch.setattr(
        transcription, "run_speaker_detection_batch_in_process", fake_batch_in_process
    )

    result = transcription.complete_folder_batch_outputs(
        output_root=output_root,
        state={
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": True,
            "speaker_count": 0,
            "GPU": True,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        progress={},
        prepared=prepared,
        failures=[],
    )

    assert len(process_calls) == 1
    assert len(process_calls[0]) == 2
    assert result["successful"] == 2
    assert result["failed"] == 0
    output_json = output_root / "one_transcript_tiny" / "transcription.json"
    assert json.loads(output_json.read_text())["segments"][0]["speaker"] == "SPEAKER_00"


def test_gpu_phase2_recovers_diarized_manifest_after_child_exit(tmp_path, monkeypatch):
    output_root = tmp_path / "transcriptions"
    output_dir = output_root / "one_transcript_tiny"
    output_dir.mkdir(parents=True)
    completed = [
        {
            "file_path": str(tmp_path / "one.mp3"),
            "file_id": "one_transcript_tiny",
            "timestamp": "2026-06-09 10-00-00",
        }
    ]
    (output_dir / transcription.DIARIZED_TRANSCRIPT_FILENAME).write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "hello",
                        "speaker": "SPEAKER_00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    transcription.write_phase2_manifest(output_root, completed, [])

    class FailedProcess:
        exitcode = -11

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def join(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(transcription, "Process", FailedProcess)

    items, failures = transcription.run_speaker_detection_batch_in_process(
        output_root=output_root,
        state={
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": True,
            "speaker_count": 0,
            "GPU": True,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        prepared=completed,
        progress={},
    )

    assert items[0]["file_id"] == "one_transcript_tiny"
    assert items[0]["transcript"]["segments"][0]["speaker"] == "SPEAKER_00"
    assert "Recovered completed diarized transcripts" in failures[0]["error"]


def test_output_failure_does_not_mark_completed_diarization_failed(tmp_path, monkeypatch):
    output_root = tmp_path / "transcriptions"
    output_dir = output_root / "one_transcript_tiny"
    output_dir.mkdir(parents=True)
    (output_dir / "metadata.txt").write_text(
        yaml.dump(
            {
                "timestamp": "2026-06-09 10-00-00",
                "transcription_status": "complete",
                "diarization_status": "complete",
                "output_status": "pending",
            }
        ),
        encoding="utf-8",
    )

    import aTrain_core.outputs as outputs

    def fail_create_output_files(*args):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(outputs, "create_output_files", fail_create_output_files)

    result = transcription.complete_folder_batch_outputs(
        output_root=output_root,
        state={
            "model": "tiny",
            "language": "auto-detect",
            "speaker_detection": True,
            "speaker_count": 0,
            "GPU": False,
            "compute_type": "int8",
            "temperature_override": None,
            "initial_prompt": None,
            "cpu_threads": 0,
        },
        progress={},
        prepared=[
            {
                "file_path": str(tmp_path / "one.mp3"),
                "file_id": "one_transcript_tiny",
                "timestamp": "2026-06-09 10-00-00",
                "transcript": {
                    "segments": [
                        {
                            "start": 0,
                            "end": 1,
                            "text": "hello",
                            "speaker": "SPEAKER_00",
                        }
                    ]
                },
            }
        ],
        failures=[],
    )

    metadata = yaml.safe_load((output_dir / "metadata.txt").read_text())

    assert result["successful"] == 0
    assert result["failed"] == 1
    assert metadata["diarization_status"] == "complete"
    assert metadata["output_status"] == "failed"

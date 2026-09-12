from pathlib import Path
from typing import Annotated

from typer import Argument, Option, Typer

from aTrain_core.globals import DEFAULT_CPU_THREADS, MAX_CPU_THREADS
from aTrain_core.load_resources import (
    download_all_models,
    get_model,
    remove_model,
)
from aTrain_core.outputs import (
    delete_transcription,
)
from aTrain_core.settings import ComputeType, Device, Settings, check_inputs_transcribe
from aTrain_core.transcribe import prepare_transcription
from aTrain_core.transcribe import transcribe as _transcribe

FILE_HELP = "Audio file to be transcribed"
MODEL_HELP = "Model used to transcribe"
LANGUAGE_HELP = "Language of the audio"
DIARIZE_HELP = "Enable speaker detection"
SPEAKER_HELP = "Number of Speakers. Use '0' to let aTrain auto-detect speaker number."
PROMPT_HELP = "Initial prompt passed to model"
DEVICE_HELP = "Hardware used to transcribe"
COMPUTE_HELP = "Data type used in computations"
TEMP_HELP = "Temperature used for sampling"
CPU_THREADS_HELP = f"Number of CPU threads to use (0 = auto, default is {DEFAULT_CPU_THREADS}). Only applies when using CPU."

FINISHED_TEXT = """Thank you for using aTrain
If you use aTrain in a scientific publication, please cite our paper:
'Take the aTrain. Introducing an interface for the Accessible Transcription of Interviews'
available under: https://doi.org/10.1016/j.jbef.2024.100891"""


cli = Typer(help="CLI for aTrain_core")


@cli.command()
def transcribe(
    file: Annotated[Path, Argument(help=FILE_HELP)],
    model: Annotated[str, Option(help=MODEL_HELP)] = "large-v3-turbo",
    language: Annotated[str, Option(help=LANGUAGE_HELP)] = "auto-detect",
    prompt: Annotated[str | None, Option(help=PROMPT_HELP)] = None,
    speaker_detection: Annotated[bool, Option(help=DIARIZE_HELP)] = False,
    speaker_count: Annotated[int, Option(help=SPEAKER_HELP)] = 0,
    device: Annotated[Device, Option(help=DEVICE_HELP)] = Device.CPU,
    compute_type: Annotated[ComputeType, Option(help=COMPUTE_HELP)] = ComputeType.INT8,
    temperature: Annotated[float | None, Option(help=TEMP_HELP, min=0.0, max=1.0)] = None,
    cpu_threads: Annotated[
        int, Option(help=CPU_THREADS_HELP, min=0, max=MAX_CPU_THREADS)
    ] = DEFAULT_CPU_THREADS,
):
    """Start transcription process for an audio file"""
    file, file_id, timestamp = prepare_transcription(file=file)
    try:
        check_inputs_transcribe(file, model, language, device)
        settings = Settings(
            file=file,
            file_id=file_id,
            file_name=file.name,
            model=model,
            language=language,
            speaker_detection=speaker_detection,
            speaker_count=speaker_count,
            device=device,
            compute_type=compute_type,
            timestamp=timestamp,
            temperature=temperature,
            initial_prompt=prompt,
            cpu_threads=cpu_threads,
        )
        _transcribe(settings)
        print(FINISHED_TEXT)
    except Exception as e:
        delete_transcription(file_id)
        raise e


@cli.command()
def load(model: Annotated[str, Argument(help="Model to download")]):
    """Download a specified transcription model"""
    if model == "all":
        download_all_models()
        print("All models downloaded")
    else:
        get_model(model)
        print(f"Model {model} downloaded")


@cli.command()
def remove(model: Annotated[str, Argument(help="Model to remove")]):
    """Remove a specified transcription model"""
    remove_model(model)
    print(f"Model {model} removed")


if __name__ == "__main__":
    cli()

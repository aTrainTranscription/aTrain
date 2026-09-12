import logging
from datetime import datetime
from importlib.resources import files
from multiprocessing.managers import DictProxy
from pathlib import Path
from typing import cast

from nicegui import ElementFilter, app, ui
from nicegui.run import tear_down as stop_transcription

GIF_PROCESS = cast(Path, files("aTrain") / "static" / "images" / "process.gif")


def dialog_process(progress: DictProxy):
    state = app.storage.general
    start_time = datetime.now()
    ui.timer(0.1, lambda: update_progress(progress, start_time)).mark("timer_process")
    with ui.dialog(value=True) as dialog, ui.card() as card:
        dialog.props("persistent").mark("dialog_process")
        card.classes("w-[500px] p-8 gap-3")
        ui.label("We are working on it!").classes("font-bold text-dark text-lg")
        ui.separator()
        ui.image(GIF_PROCESS).classes("w-1/2 h-1/2 mx-auto")
        with ui.row().classes("gap-1"):
            lbl_task = ui.label().classes("font-bold text-dark")
            lbl_task.bind_text_from(state, "task_number", lambda x: f"{x}:")
            ui.label("").bind_text(state, "task")
        progress_bar = ui.linear_progress(show_value=False, color="dark")
        progress_bar.bind_value(state, "progress").props("animation-speed=500")
        with ui.row().classes("w-full justify-between items-center"):
            with ui.column().classes("gap-1"):
                ui.label("").bind_text_from(
                    state, "GPU", lambda x: "Running on " + ("GPU" if x else "CPU")
                )
                ui.label("").bind_text_from(state, "time", lambda x: f"Time: {x}")
            btn_stop = ui.button("stop", color="dark").props("unelevated no-caps")
        btn_stop.on_click(stop_transcription)


def update_progress(progress: DictProxy, start_time: datetime):
    state = app.storage.general
    try:
        current = progress["current"]
        total = progress["total"]
        task = progress["task"]
        file_index = progress.get("file_index", 0)
        file_total = progress.get("file_total", 0)
        progress_index = progress.get("progress_index", file_index)
        progress_total = progress.get("progress_total", file_total)
        file_name = progress.get("file_name", "")
    except (EOFError, ConnectionError, FileNotFoundError) as e:
        # The manager process backing `progress` dies while a cancelled
        # transcription tears down; a late timer tick would otherwise log a
        # pseudo-crash (BrokenPipeError) right before the timer is cancelled.
        # Log it: if the manager dies for any *other* reason the dialog would
        # otherwise freeze on stale storage values with no trace at all.
        logging.getLogger(__name__).debug("progress proxy unavailable: %r", e)
        return
    if progress_total:
        state["progress"] = (progress_index + (current / total)) / progress_total
        file_name = clean_progress_file_name(file_name)
    else:
        state["progress"] = current / total
        file_name = ""
    if file_total:
        stage_number, stage_total, stage_label = folder_stage(task, state["speaker_detection"])
        state["task_number"] = f"File {file_index + 1} of {file_total}"
        state["task"] = f"Stage {stage_number}/{stage_total}: {stage_label}"
        if file_name:
            state["task"] = f"{state['task']} - {file_name}"
    else:
        total_tasks = 3 if state["speaker_detection"] else 2
        current_task = {"Prepare": 1, "Transcribe": 2, "Detect Speakers": 3}[task]
        state["task_number"] = f"Task {current_task}/{total_tasks}"
        state["task"] = task
    update_time(start_time)


def clean_progress_file_name(file_name: str) -> str:
    for prefix in ("Transcribe: ", "Diarize: ", "Write: "):
        if file_name.startswith(prefix):
            return file_name.removeprefix(prefix)
    return file_name


def folder_stage(task: str, speaker_detection: bool) -> tuple[int, int, str]:
    if not speaker_detection:
        return 1, 1, "Transcription"
    if task == "Detect Speakers":
        return 2, 2, "Speaker diarization"
    return 1, 2, "Transcription"


def update_time(start_time: datetime):
    state = app.storage.general
    timedelta = datetime.now() - start_time
    total_seconds = int(timedelta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    state["time"] = f"{hours:02}:{minutes:02}:{seconds:02}"


def close_dialog_process():
    try:
        timers = ElementFilter(marker="timer_process", kind=ui.timer)
        dialogs = ElementFilter(marker="dialog_process", kind=ui.dialog)
    except RuntimeError as exc:
        deleted_context_messages = (
            "client this element belongs to has been deleted",
            "parent element this slot belongs to has been deleted",
        )
        if any(message in str(exc) for message in deleted_context_messages):
            return
        raise
    for timer in timers:
        timer.cancel()
    for dialog in dialogs:
        dialog.delete()

import logging
from datetime import datetime
from importlib.resources import files
from multiprocessing.managers import DictProxy
from pathlib import Path
from typing import cast

from aTrain.utils.stop import stop_run
from nicegui import ElementFilter, app, ui

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
            lbl_task.bind_text_from(state, "task_number", lambda x: f"Task {x}:")
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
        btn_stop.on_click(stop_run)


def update_progress(progress: DictProxy, start_time: datetime):
    state = app.storage.general
    try:
        current, total, task = progress["current"], progress["total"], progress["task"]
    except (EOFError, ConnectionError, FileNotFoundError) as e:
        # The manager process backing `progress` dies while a cancelled
        # transcription tears down; a late timer tick would otherwise log a
        # pseudo-crash (BrokenPipeError) right before the timer is cancelled.
        # Log it: if the manager dies for any *other* reason the dialog would
        # otherwise freeze on stale storage values with no trace at all.
        logging.getLogger(__name__).debug("progress proxy unavailable: %r", e)
        return
    state["progress"] = current / total
    state["task"] = task
    total_tasks = 3 if state["speaker_detection"] else 2
    current_task = {"Prepare": 1, "Transcribe": 2, "Detect Speakers": 3}[task]
    state["task_number"] = f"{current_task}/{total_tasks}"
    update_time(start_time)


def update_time(start_time: datetime):
    state = app.storage.general
    timedelta = datetime.now() - start_time
    total_seconds = int(timedelta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    state["time"] = f"{hours:02}:{minutes:02}:{seconds:02}"


def close_dialog_process():
    for timer in ElementFilter(marker="timer_process", kind=ui.timer):
        timer.cancel()
    for dialog in ElementFilter(marker="dialog_process", kind=ui.dialog):
        dialog.delete()

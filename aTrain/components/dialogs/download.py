from datetime import datetime
from importlib.resources import files
from multiprocessing.managers import DictProxy
from pathlib import Path
from typing import cast

from nicegui import ElementFilter, app, ui
from nicegui.run import tear_down as stop_download

GIF_DOWNLOAD = cast(Path, files("aTrain") / "static" / "images" / "download.gif")


def dialog_download(progress: DictProxy, model: str):
    state = app.storage.general
    start_time = datetime.now()
    ui.timer(0.1, lambda: update_progress(progress, start_time)).mark("timer_download")
    with ui.dialog(value=True) as dialog, ui.card() as card:
        dialog.props("persistent").mark("dialog_download")
        card.classes("w-[500px] p-8 gap-3")
        header_text = ui.label(f"We download the {model} model for you!")
        header_text.classes("font-bold text-dark text-lg")
        ui.separator()
        ui.image(GIF_DOWNLOAD).classes("w-1/2 h-1/2 mx-auto")
        progress_bar = ui.linear_progress(show_value=False, color="dark")
        progress_bar.bind_value(state, "progress").props("animation-speed=500")
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("").bind_text_from(state, "time", lambda x: f"Time: {x}")
            btn_stop = ui.button("stop", color="dark").props("unelevated no-caps")

        btn_stop.on_click(stop_download)


def update_progress(progress: DictProxy, start_time: datetime):
    app.storage.general["progress"] = progress["current"] / progress["total"]
    update_time(start_time)


def close_dialog_download():
    for timer in ElementFilter(marker="timer_download", kind=ui.timer):
        timer.cancel()
    for dialog in ElementFilter(marker="dialog_download", kind=ui.dialog):
        dialog.delete()


def update_time(start_time: datetime):
    state = app.storage.general
    timedelta = datetime.now() - start_time
    total_seconds = int(timedelta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    state["time"] = f"{hours:02}:{minutes:02}:{seconds:02}"

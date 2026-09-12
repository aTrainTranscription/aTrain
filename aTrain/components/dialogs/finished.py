from importlib.resources import files
from pathlib import Path
from typing import cast

from aTrain.utils.archive import open_directory_path, open_file_directory
from nicegui import app, ui

GIF_FINISHED = cast(Path, files("aTrain") / "static" / "images" / "success.gif")


def dialog_finished(file_id: str):
    state = app.storage.general
    with ui.dialog(value=True).props("persistent"), ui.card() as card:
        card.classes("w-[500px] p-8 gap-3")
        header_text = ui.label("We finished the transcription!")
        header_text.classes("font-bold text-dark text-lg")
        ui.separator()
        ui.image(GIF_FINISHED).classes("w-1/2 h-1/2 mx-auto")
        ui.separator()
        with ui.row().classes("justify-between w-full items-center"):
            ui.label("").bind_text_from(state, "time", lambda x: f"We transcribed your file in {x}")
            with ui.row():
                btn_open = ui.button("Open", color="gray-200")
                btn_open.props("unelevated no-caps text-color=dark")
                btn_exit = ui.button("Exit", color="dark")
                btn_exit.props("unelevated no-caps")

        btn_exit.on_click(ui.navigate.reload)
        btn_open.on_click(lambda: open_file_directory(file_id))


def dialog_batch_finished(output_directory: Path, successful: int, failed: int):
    state = app.storage.general
    with ui.dialog(value=True).props("persistent"), ui.card() as card:
        card.classes("w-[500px] p-8 gap-3")
        header_text = ui.label("We finished the folder transcription!")
        header_text.classes("font-bold text-dark text-lg")
        ui.separator()
        ui.image(GIF_FINISHED).classes("w-1/2 h-1/2 mx-auto")
        ui.separator()
        ui.label(f"Completed: {successful} file(s), failed: {failed} file(s)")
        ui.label(f"Output folder: {output_directory}")
        ui.separator()
        with ui.row().classes("justify-between w-full items-center"):
            ui.label("").bind_text_from(state, "time", lambda x: f"We processed your folder in {x}")
            with ui.row():
                btn_open = ui.button("Open", color="gray-200")
                btn_open.props("unelevated no-caps text-color=dark")
                btn_exit = ui.button("Exit", color="dark")
                btn_exit.props("unelevated no-caps")

        btn_exit.on_click(ui.navigate.reload)
        btn_open.on_click(lambda: open_directory_path(output_directory))

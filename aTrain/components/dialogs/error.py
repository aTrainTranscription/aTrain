from importlib.resources import files
from pathlib import Path
from typing import cast

from nicegui import ui

GIF_ERROR = cast(Path, files("aTrain") / "static" / "images" / "warning.gif")


def dialog_error(error: str, traceback: str, on_retry=None):
    """`on_retry`: also offer "Retry", which closes the dialog and calls it."""
    with ui.dialog(value=True).props("persistent") as dialog, ui.card() as card:
        card.classes("w-[500px] p-8 gap-3")
        ui.label("We encountered an error!").classes("font-bold text-dark text-lg")
        ui.separator()
        ui.image(GIF_ERROR).classes("w-1/2 h-1/2 mx-auto")
        with ui.column().classes("gap-1"):
            ui.label("The following error occured:").classes("font-bold text-dark")
            ui.label(error)
        ui.separator()
        with ui.expansion("Show Traceback").classes("bg-gray-200 w-full"):
            lbl_traceback = ui.label(traceback)
            lbl_traceback.classes("overflow-scroll w-full font-light text-xs p-2")
        ui.separator()
        with ui.row().classes("justify-between w-full items-center"):
            btn_copy = ui.button("Copy Error", color="gray-200", icon="content_copy")
            btn_copy.props("unelevated no-caps text-color=dark size=0.8rem")
            if on_retry is not None:
                btn_retry = ui.button("Retry", color="gray-200", icon="replay")
                btn_retry.props("unelevated no-caps text-color=dark size=0.8rem")
                btn_retry.on_click(lambda: (dialog.close(), on_retry()))
            btn_exit = ui.button("Exit", color="dark")
            btn_exit.props("unelevated no-caps")
        btn_copy.on_click(lambda: copy_error(error, traceback))
        btn_exit.on_click(ui.navigate.reload)


def copy_error(error: str, traceback: str):
    text = f"Error: {error}\n\n{traceback}"
    ui.clipboard.write(text)
    ui.notify("Error copied")

from aTrain.components.dialogs.delete import dialog_delete
from aTrain.layouts.base import base_layout
from aTrain.utils.archive import delete_transcription as delete
from aTrain.utils.archive import download_file_directory as download
from aTrain.utils.archive import open_file_directory as show
from aTrain.utils.archive import read_archive
from nicegui import app, ui


@ui.page("/archive")
def page():
    transcriptions = read_archive()

    with base_layout():
        with ui.row().classes("justify-between w-full"):
            ui.label("Archive").classes("text-lg text-dark font-bold")
            with ui.row():
                btn_show_all = ui.button("Show All", color="dark")
                btn_show_all.props("size=0.8rem unelevated no-caps")
                btn_show_all.on_click(lambda: show("all"))

                btn_del_all = ui.button("Delete All", color="gray-100")
                btn_del_all.props("size=0.8rem unelevated no-caps")
                btn_del_all.on_click(dialog_delete)

        with ui.list().classes("w-full").props("separator"):
            with ui.item():
                with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                    grid.classes("w-full text-grey text-xs items-end")
                    ui.label("#")
                    ui.label("Date")
                    ui.label("Input")
                    ui.label("Actions")
            for i, transcription in enumerate(transcriptions):
                with ui.item().classes("hover:bg-gray-100"):
                    with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                        grid.classes("w-full items-center")
                        ui.label(str(i + 1)).classes("text-medium")
                        ui.label(transcription["timestamp"]).classes("font-light")
                        ui.label(transcription["filename"]).classes("font-light")
                        with ui.row():
                            btn_open = ui.button(
                                "download" if app.native.main_window is None else "open",
                                color="dark",
                            )
                            btn_open.props("no-caps size=0.7rem unelevated")
                            btn_delete = ui.button("delete", color="gray-100")
                            btn_delete.props("no-caps size=0.7rem unelevated")
                btn_open.on_click(
                    lambda t=transcription: (
                        download(t["file_id"])
                        if app.native.main_window is None
                        else show(t["file_id"])
                    )
                )
                btn_delete.on_click(
                    lambda t=transcription: (delete(t["file_id"]), ui.navigate.reload())
                )

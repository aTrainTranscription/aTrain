from pathlib import Path

from aTrain.components.settings.advanced import advanced_settings
from aTrain.components.settings.file import input_file
from aTrain.components.settings.language import input_language
from aTrain.components.settings.model import input_model
from aTrain.components.settings.speaker_count import input_speaker_count
from aTrain.components.settings.speaker_detection import input_speaker_detection
from aTrain.components.splash_screen import splash_screen
from aTrain.layouts.base import base_layout
from aTrain.utils.transcription import (
    start_folder_transcription,
    start_transcription,
    start_transcription_from_path,
)
from aTrain_core.globals import FLATPAK, LINUX
from nicegui import Client, ui


@ui.page("/")
async def page(client: Client):
    await client.connected()
    await splash_screen()
    with base_layout():
        with ui.element("div").classes(
            "w-full h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-10"
        ):
            file = input_file()
            input_model()
            input_language()
            input_speaker_detection()
            input_speaker_count()
        ui.separator().classes("mt-4")
        with ui.row().classes("w-full justify-between items-center"):
            settings_btn = ui.button("Advanced Settings", color="gray-100").mark(
                "open_advanced_settings"
            )
            settings_btn.props("size=0.8rem unelevated no-caps icon=settings")
            if FLATPAK or LINUX:

                async def start_from_selected():
                    if getattr(file, "selection_mode", None) == "folder":
                        if not getattr(file, "selected_folder_path", None):
                            ui.notify("Please select a folder first", color="negative")
                            return
                        await start_folder_transcription(Path(file.selected_folder_path))
                        return
                    if not getattr(file, "selected_path", None):
                        ui.notify("Please select a file first", color="negative")
                        return
                    await start_transcription_from_path(
                        Path(file.selected_path), file.selected_name
                    )

                start_btn = ui.button("Start", on_click=start_from_selected, color="dark")
            else:

                async def start_from_upload_or_folder():
                    if getattr(file, "selection_mode", None) == "folder":
                        if not getattr(file, "selected_folder_path", None):
                            ui.notify("Please select a folder first", color="negative")
                            return
                        await start_folder_transcription(Path(file.selected_folder_path))
                        return
                    file.upload()

                start_btn = ui.button("Start", on_click=start_from_upload_or_folder, color="dark")
            start_btn.props("no-caps unelevated")
            advanced_settings(open=False)

    if not (FLATPAK or LINUX):
        file.on_upload(start_transcription)
    settings_btn.on_click(lambda: advanced_settings(open=True))

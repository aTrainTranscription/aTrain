from aTrain.components.queue_status import queue_status
from aTrain.components.settings.advanced import seed_defaults
from aTrain.components.settings.file import input_file
from aTrain.components.settings.language import input_language
from aTrain.components.settings.model import input_model
from aTrain.components.settings.speaker_count import input_speaker_count
from aTrain.components.settings.speaker_detection import input_speaker_detection
from aTrain.components.splash_screen import splash_screen
from aTrain.layouts.base import base_layout
from aTrain.utils.transcription import start_paths, start_uploads
from aTrain_core.globals import FLATPAK, LINUX
from nicegui import Client, app, ui


@ui.page("/")
async def page(client: Client):
    await client.connected()
    await splash_screen()
    if client.is_deleted:
        return  # the window loaded the page again while the splash screen was waiting
    # Imported here: it loads the engine modules (the splash screen has loaded torch by now).
    from aTrain.utils import queue_ui
    from aTrain_core.jobs import QueueLockedError

    try:
        service = await queue_ui.get_queue_service()
    except QueueLockedError:
        service = None
    locked = service is None
    seed_defaults()
    with base_layout():
        if locked:
            ui.label(queue_ui.LOCKED_TEXT).classes("w-full p-3 bg-amber-100 text-dark rounded")
        portal = (FLATPAK or LINUX) and app.native.main_window is not None

        async def start():
            if file.selected_paths:  # picked files or a folder on disk
                await start_paths(file.selected_paths, file.export_dir)
            elif portal or file.mode.value == "Folder":
                ui.notify("Please select a file or a folder with files first", color="negative")
            else:
                file.upload()  # browser upload; start_uploads runs when it's done

        with ui.element("div").classes(
            "w-full h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-10"
        ):
            file = input_file()
            input_model()
            input_language()
            input_speaker_detection()
            input_speaker_count()
            # third column even while Number of Speakers is hidden
            with ui.element("div").classes(
                "self-stretch flex items-end justify-end lg:col-start-3"
            ):
                start_btn = ui.button("Start", on_click=start, color="dark")
                start_btn.props("no-caps unelevated")
            if locked:
                start_btn.disable()
        ui.separator().classes("mt-4")
        if not locked:
            queue_status(service, start_btn)

    file.on_multi_upload(start_uploads)

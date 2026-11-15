from pathlib import Path

from aTrain.components.queue_status import queue_status
from aTrain.components.settings.advanced import seed_defaults
from aTrain.components.settings.file import input_file
from aTrain.components.settings.language import input_language
from aTrain.components.settings.model import input_model
from aTrain.components.settings.speakers import input_speakers
from aTrain.components.splash_screen import splash_screen
from aTrain.layouts.base import base_layout
from aTrain.utils.transcription import stage_upload, start_paths
from aTrain_core.globals import FLATPAK, LINUX, MACOS
from nicegui import Client, app, ui


@ui.page("/")
async def page(client: Client):
    await client.connected()
    if client.is_deleted:
        return
    await splash_screen()
    if client.is_deleted:
        return
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
        with ui.element("div").classes(
            "w-full h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-10"
        ):
            file = input_file()
            input_model()
            input_language()
            input_speakers()
        ui.separator().classes("mt-4")
        with ui.row().classes("w-full justify-end items-center"):

            def update_add():
                add.text = "Add to queue" if service is None or service.jobs() else "Transcribe"

            async def added(path: Path) -> bool:
                ok = await start_paths([path])
                if ok:
                    update_add()
                    open_list()
                return ok

            if (FLATPAK or LINUX or MACOS) and app.native.main_window is not None:

                async def start_from_selected():
                    if not getattr(file, "selected_path", None):
                        ui.notify("Please select a file first", color="negative")
                        return
                    await added(Path(file.selected_path))

                add = ui.button(on_click=start_from_selected, color="dark")
            else:
                add = ui.button(on_click=file.upload, color="dark")
            add.props("no-caps unelevated").mark("add_to_queue")
            add.set_enabled(not locked)
            update_add()
        open_list = queue_status(service) if not locked else lambda: None

    if not (FLATPAK or LINUX or MACOS) or app.native.main_window is None:

        async def add_upload(e):
            if await added(await stage_upload(e.file)):
                file.reset()
                file.set_select()

        file.on_upload(add_upload)

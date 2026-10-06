from aTrain.components.queue_status import queue_status
from aTrain.components.settings.advanced import seed_defaults
from aTrain.components.settings.file import input_file
from aTrain.components.settings.language import input_language
from aTrain.components.settings.model import input_model
from aTrain.components.settings.speakers import input_speakers
from aTrain.components.splash_screen import splash_screen
from aTrain.layouts.base import base_layout
from nicegui import Client, ui


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

        def update_add():
            count = len(files.names)
            add.text = f"Add {count} files to queue" if count > 1 else "Add to queue"
            add.set_enabled(bool(count) and not files.uploading and not locked)

        async def add_to_queue():
            await files.submit()
            open_list()

        with ui.element("div").classes(
            "w-full grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_300px] gap-8"
        ):
            files = input_file(on_change=lambda: update_add())
            with ui.column().classes("w-full gap-3.5"):
                input_model()
                input_language()
                input_speakers()
                add = ui.button("Add to queue", on_click=add_to_queue, color="dark")
                add.props("no-caps unelevated").classes("w-full h-11 mt-1").mark("add_to_queue")
        update_add()
        open_list = queue_status(service) if not locked else lambda: None

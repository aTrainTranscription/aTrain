"""The Queue tab: everything that is queued, running or finished."""

from aTrain.components.queue_view import queue_view
from aTrain.layouts.base import base_layout
from nicegui import ui


@ui.page("/queue")
async def page():
    # Imported here: it loads the engine modules, which the other pages don't need.
    from aTrain.utils import queue_ui
    from aTrain_core.jobs import QueueLockedError

    try:
        service = await queue_ui.get_queue_service()
    except QueueLockedError:
        service = None
    with base_layout():
        if service is None:
            ui.label("Queue").classes("text-lg text-dark font-bold")
            ui.label(queue_ui.LOCKED_TEXT).classes("w-full p-3 bg-amber-100 text-dark rounded")
        else:
            queue_view(service)

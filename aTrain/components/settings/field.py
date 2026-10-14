from contextlib import contextmanager

from nicegui import ui


@contextmanager
def field(label: str):
    """A setting on the transcribe page: a small label above its control."""
    with ui.column().classes("w-full gap-1.5"):
        ui.label(label).classes("text-[13px] font-medium text-gray-600")
        yield


def style_select(select: ui.select) -> ui.select:
    return select.classes("w-full").props("filled dense bg-color=gray-100 color=dark")

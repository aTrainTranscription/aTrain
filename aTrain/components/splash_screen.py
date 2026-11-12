import importlib
import sys
from importlib.resources import files
from pathlib import Path
from typing import cast

from nicegui import run, ui

ATRAIN_LOGO = cast(Path, files("aTrain") / "static" / "images" / "logo.svg")


async def splash_screen():
    # A failed transcribe import can leave torch loaded; retry on the next visit.
    if "torch" not in sys.modules or "aTrain_core.transcribe" not in sys.modules:
        with ui.column().classes("gap-0") as splash:
            splash.classes("w-full h-[90vh] items-center justify-center")
            logo = ui.image(ATRAIN_LOGO).props("height=90px width=240px fit=contain")
            logo.classes("mb-5")
            ui.label("Starting Application").classes("text-dark")
            ui.spinner("dots", size="2em", color="dark")
        # Import in threads for improved startup speed
        await run.io_bound(importlib.import_module, name="torch")
        await run.io_bound(importlib.import_module, name="aTrain_core.transcribe")
        splash.delete()

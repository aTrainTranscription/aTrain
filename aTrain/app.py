import os
import sys
from pathlib import Path
from typing import Annotated, cast

from aTrain_core.globals import ATRAIN_DIR, FLATPAK, REQUIRED_MODELS
from aTrain_core.load_resources import get_model
from typer import Option, Typer

cli = Typer(help="CLI for aTrain.")


@cli.command()
def init():
    """Download all required model for aTrain."""
    for model in REQUIRED_MODELS:
        get_model(model=model)


@cli.command()
def start(
    native: Annotated[bool, Option(help="Run in a native window")] = True,
    reload: Annotated[bool, Option(help="Reload on code change")] = False,
    port: Annotated[
        int, Option(help="Starting port for the web server; next free port is used")
    ] = 8080,
):
    """Start aTrain (requires GUI extras — install with `pip install 'aTrain[gui]'`)."""
    # Lazy imports: keep the GUI stack out of the import chain so headless
    # installs (no [gui] extras) can still run `aTrain init` and `aTrain --help`.
    try:
        from importlib.resources import files
        from unittest.mock import patch

        from platformdirs import user_config_path

        nicegui_storage_path = (
            user_config_path() / "aTrain" if FLATPAK else (ATRAIN_DIR / "settings")
        )
        with patch.dict(os.environ, NICEGUI_STORAGE_PATH=str(nicegui_storage_path)):
            from nicegui import ui

            from aTrain.pages import about, archive, faq, models, transcribe  # noqa
        from wakepy import keep
    except ImportError as e:
        sys.exit(
            f"Error: GUI extras missing — '{e.name}' is not installed.\n"
            "Install them with: pip install 'aTrain[gui]'"
        )

    from aTrain.utils.ports import find_available_port

    print("Running aTrain")
    selected_port = find_available_port(port)
    if selected_port != port:
        print(f"Port {port} is busy, using {selected_port} instead")
    if FLATPAK:
        ui.run(
            native=native,
            reload=reload,
            port=selected_port,
            title="aTrain",
            favicon=cast(Path, files("aTrain") / "static" / "favicon.ico"),
            window_size=(1280, 720) if native else None,
        )
    else:
        with keep.running():
            ui.run(
                native=native,
                reload=reload,
                port=selected_port,
                title="aTrain",
                favicon=cast(Path, files("aTrain") / "static" / "favicon.ico"),
                window_size=(1280, 720) if native else None,
            )

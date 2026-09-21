from collections.abc import Callable

from nicegui import ui

CRISPERWHISPER_LICENSE = (
    "https://huggingface.co/aTrain-core/CrisperWhisper2_large/blob/"
    "20638bbea0625a8b0883c445a25dbe21f94c62aa/LICENSE.md"
)


def dialog_crisperwhisper_license(on_accept: Callable[[], object]) -> None:
    """Request acceptance of CrisperWhisper's license before downloading it."""

    with ui.dialog(value=True) as dialog, ui.card().classes("w-[500px] p-8 gap-3"):
        dialog.props("persistent").mark("dialog_crisperwhisper_license")
        ui.label("CrisperWhisper license confirmation").classes("font-bold text-dark text-lg")
        ui.separator()
        ui.label(
            "The CrisperWhisper 2.0 model weights are licensed under the nyra health "
            "Non-Commercial Research License, © 2026 nyra health GmbH, Vienna, Austria. "
            "All rights reserved. Commercial licenses are available from nyra health GmbH. "
            "The accompanying inference code is licensed separately under the MIT License."
        )
        ui.link("View license", target=CRISPERWHISPER_LICENSE, new_tab=True).classes("text-dark")
        with ui.row().classes("w-full justify-end"):
            btn_cancel = ui.button("Cancel", color="gray-100")
            btn_cancel.props("unelevated no-caps text-color=dark")
            btn_cancel.on_click(dialog.close)
            btn_accept = ui.button("Accept", color="dark")
            btn_accept.props("unelevated no-caps")

            def accept() -> object:
                dialog.close()
                return on_accept()

            btn_accept.on_click(accept)

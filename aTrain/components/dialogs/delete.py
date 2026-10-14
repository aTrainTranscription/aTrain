from aTrain.utils.archive import delete_all_transcriptions
from nicegui import ui


def dialog_delete():
    async def confirm():
        btn_confirm.disable()
        btn_cancel.disable()
        try:
            await delete_all_transcriptions()
        except Exception as e:
            ui.notify(
                f"Could not delete all transcriptions: {e}", color="negative", multi_line=True
            )
        else:
            dialog.close()
            ui.navigate.reload()
        finally:
            btn_confirm.enable()
            btn_cancel.enable()

    with ui.dialog(value=True) as dialog, ui.card().classes("p-8"):
        dialog.props("persistent")
        ui.label("Are you sure you want to delete all transcriptions?")
        ui.label(
            "This also stops all unfinished jobs and deletes the queue and its temporary files."
        )
        ui.separator()
        with ui.row().classes("w-full justify-end"):
            btn_cancel = ui.button("Cancel", color="gray-100").on_click(dialog.close)
            btn_cancel.props("unelevated no-caps text-color=dark")
            btn_confirm = ui.button("Confirm", color="dark")
            btn_confirm.props("unelevated no-caps")
            btn_confirm.on_click(confirm)

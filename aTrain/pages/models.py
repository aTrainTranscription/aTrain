from aTrain.layouts.base import base_layout
from aTrain.utils.models import download_model, read_model_metadata, remove_model
from aTrain_core.globals import is_packaged_model
from nicegui import ui


@ui.page("/models")
def page():
    all_models = read_model_metadata()
    # Hide only what the user genuinely cannot manage: models that ship inside
    # the (read-only) install dir. Filtering by REQUIRED_MODELS membership hid
    # large-v3-turbo from slim builds too, where it is not bundled - leaving the
    # default model unreachable, since the transcribe page lists only models
    # already on disk.
    models = [model for model in all_models if not is_packaged_model(model["model"])]
    with base_layout():
        ui.label("Model Manager").classes("text-lg text-dark font-bold")
        with ui.list().classes("w-full").props("separator"):
            with ui.item():
                with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                    grid.classes("w-full text-grey text-xs items-end")
                    ui.label("#")
                    ui.label("Model")
                    ui.label("Download Size")
                    ui.label("Actions")
            for i, model in enumerate(models):
                with ui.item().classes("hover:bg-gray-100"):
                    with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                        grid.classes("w-full items-center")
                        ui.label(str(i + 1)).classes("font-light")
                        ui.label(model["model"]).classes("font-medium")
                        ui.label(model["size"]).classes("font-light")
                        with ui.row():
                            if model["downloaded"]:
                                btn_delete = ui.button("Delete", color="gray-100")
                                btn_delete.props("no-caps size=0.7rem unelevated")
                                btn_delete.on_click(
                                    lambda m=model: (
                                        remove_model(m["model"]),
                                        ui.navigate.reload(),
                                    )
                                )
                            else:
                                btn_download = ui.button("Download", color="dark")
                                btn_download.props("no-caps size=0.7rem unelevated")
                                btn_download.on_click(lambda m=model: download_model(m["model"]))

from aTrain.components.dialogs.license import dialog_crisperwhisper_license
from aTrain.layouts.base import base_layout
from aTrain.utils.models import download_model, read_model_metadata, remove_model
from aTrain_core.globals import is_packaged_model
from nicegui import ui

MODEL_GROUPS = ("Recommended", "Language Specific", "All others")


@ui.page("/models")
def page():
    all_models = read_model_metadata()
    # Hide only what the user genuinely cannot manage: models that ship inside
    # the (read-only) install dir. Filtering by REQUIRED_MODELS membership hid
    # large-v3-turbo from slim builds too, where it is not bundled - leaving the
    # default model unreachable, since the transcribe page lists only models
    # already on disk.
    models = [model for model in all_models if not is_packaged_model(model["model"])]
    grouped_models = {group: [] for group in MODEL_GROUPS}
    for model in models:
        group = model.get("group", "All others")
        grouped_models[group if group in grouped_models else "All others"].append(model)

    with base_layout():
        ui.label("Model Manager").classes("text-lg text-dark font-bold")
        for group in MODEL_GROUPS:
            group_models = grouped_models[group]
            if not group_models:
                continue
            with (
                ui.expansion(group, value=group == "Recommended")
                .classes("w-full")
                .mark(f"model_group_{group.lower().replace(' ', '_')}")
            ):
                with ui.list().classes("w-full").props("separator"):
                    with ui.item():
                        with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                            grid.classes("w-full text-grey text-xs items-end")
                            ui.label("#")
                            ui.label("Model")
                            ui.label("Download Size")
                            ui.label("Actions")
                    for i, model in enumerate(group_models):
                        with ui.item().classes("hover:bg-gray-100"):
                            with ui.grid(columns="minmax(0, 60px) 1fr 1fr 1fr") as grid:
                                grid.classes("w-full items-center")
                                ui.label(str(i + 1)).classes("font-light")
                                with ui.row(align_items="center").classes("gap-1"):
                                    ui.label(model.get("display_name", model["model"])).classes(
                                        "font-medium"
                                    )
                                    if info := model.get("info"):
                                        ui.icon("info_outline", size="sm", color="grey").tooltip(
                                            info
                                        ).mark(f"model_info_{model['model']}")
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
                                        if model["model"] == "crisperwhisper-v2-large":
                                            btn_download.on_click(
                                                lambda m=model: dialog_crisperwhisper_license(
                                                    lambda: download_model(m["model"])
                                                )
                                            )
                                        else:
                                            btn_download.on_click(
                                                lambda m=model: download_model(m["model"])
                                            )

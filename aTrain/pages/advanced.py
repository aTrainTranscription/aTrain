from aTrain.components.settings.advanced import advanced_settings_body
from aTrain.layouts.base import base_layout
from nicegui import ui


@ui.page("/advanced")
def page():
    with base_layout():
        ui.label("Advanced Settings").classes("text-lg text-dark font-bold")
        ui.separator()
        advanced_settings_body()

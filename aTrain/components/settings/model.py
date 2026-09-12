from aTrain.components.settings.language import update_language_options
from aTrain.utils.models import read_transcription_models
from aTrain_core.globals import REQUIRED_MODELS
from nicegui import app, ui


def input_model():
    with ui.column().classes("gap-2"):
        ui.label("Select Model").classes("font-bold text-dark text-md")
        ui.separator()
        options = get_model_options()
        with ui.select(options=options).classes("w-full") as input:
            input.classes("w-full")
            input.props("filled bg-color=gray-100 color=dark")
            input.mark("select_model")
            if not options:
                # A fresh slim install has nothing on disk yet, and this list
                # shows only downloaded models - without a hint it reads as a
                # broken app rather than a missing download.
                input.props('label="No models yet"')
                input.props('hint="Download one under Models"')

    input.bind_value(app.storage.general, "model")
    input.on_value_change(update_language_options)


def get_model_options() -> list:
    state = app.storage.general
    options = read_transcription_models()
    if state.get("model") in options:
        active = state.get("model")
    elif REQUIRED_MODELS[1] in options:
        active = REQUIRED_MODELS[1]
    elif options:
        active = options[0]
    else:
        active = None
    state["model"] = active
    return options

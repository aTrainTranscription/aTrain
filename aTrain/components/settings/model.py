import json

from aTrain.components.settings.field import field, style_select
from aTrain.components.settings.language import update_language_options
from aTrain.utils.models import read_transcription_models
from aTrain_core.globals import REQUIRED_MODELS
from aTrain_core.load_resources import load_model_config_file
from nicegui import app, ui


def input_model():
    with field("Model"):
        options = get_model_options()
        input = style_select(ui.select(options=options)).mark("select_model")
        if not options:
            # A fresh slim install has nothing on disk yet, and this list
            # shows only downloaded models - without a hint it reads as a
            # broken app rather than a missing download.
            input.props('label="No models yet"')
            input.props('hint="Download one under Models"')
        # Each option shows the model's description from models.json as a second line.
        infos = json.dumps(model_infos(options)).replace("<", "\\u003c")
        input.add_slot(
            "option",
            f"""
            <q-item v-bind="props.itemProps">
                <q-item-section>
                    <q-item-label>{{{{ props.opt.label }}}}</q-item-label>
                    <q-item-label caption>{{{{ ({infos})[props.opt.label] }}}}</q-item-label>
                </q-item-section>
            </q-item>
            """,
        )

    input.bind_value(app.storage.general, "model")
    input.on_value_change(update_language_options)


def model_infos(models: list) -> dict[str, str]:
    config = load_model_config_file()
    return {model: config.get(model, {}).get("info", "") for model in models}


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

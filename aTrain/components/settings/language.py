from aTrain.components.settings.field import field, style_select
from aTrain.utils.models import model_languages
from nicegui import ElementFilter, app, ui


def input_language():
    with field("Language"):
        select = style_select(ui.select(options=get_language_options()))
        select.mark("select_language").bind_value(app.storage.general, "language")


def get_language_options() -> dict:
    state = app.storage.general
    model = state.get("model")
    language = state.get("language")
    options = model_languages(model) if model else {}
    if language in options:
        active = language
    elif options:
        active = list(options.keys())[0]
    else:
        active = None
    state["language"] = active
    return options


def update_language_options():
    state = app.storage.general
    for select in ElementFilter(marker="select_language", kind=ui.select):
        select.set_options(get_language_options(), value=state.get("language"))

"""Speaker detection and the number of speakers, in one select."""

from aTrain.components.settings.field import field, style_select
from nicegui import app, ui

OPTIONS = {"off": "Off", "auto": "Detect automatically", 2: "2 speakers", 3: "3 speakers"}
CUSTOM_ERROR = "Enter a whole number from 3 to 99."


def speakers_value(state) -> str | int:
    """The select's value for the stored settings."""
    if not state.get("speaker_detection"):
        return "off"
    return int(state.get("speaker_count") or 0) or "auto"


def speaker_settings(value: str | int) -> dict:
    """The job settings for a value of the select."""
    if value == "off":
        return {"speaker_detection": False, "speaker_count": None}
    if value == "auto":
        return {"speaker_detection": True, "speaker_count": None}
    return {"speaker_detection": True, "speaker_count": int(value)}


def custom_count(value) -> int | None:
    """A typed number of speakers if it is a whole number from 3 to 99, else None."""
    if value is None or value != int(value) or not 3 <= value <= 99:
        return None
    return int(value)


def options_with(value: str | int) -> dict:
    options = dict(OPTIONS)
    if value not in options:
        options[value] = f"{value} speaker{'' if value == 1 else 's'}"
    return options


def input_speakers():
    state = app.storage.general
    value = speakers_value(state)
    state.update(speaker_settings(value))
    with field("Speakers"):
        select = style_select(ui.select(options_with(value), value=value)).mark("select_speakers")
        # "More" below the options: a number of speakers that isn't listed
        with select.add_slot("after-options"):
            with ui.row().classes(
                "items-center gap-2 px-3.5 py-2 border-t border-gray-100 no-wrap"
            ):
                ui.label("More").classes("text-sm text-gray-600")
                number = ui.number(placeholder="3-99", min=3, max=99, step=1)
                number.props("dense borderless input-class=px-2.5").classes(
                    "flex-1 min-w-0 bg-gray-100 rounded"
                ).mark("number_speakers")
                ui.button("Set", on_click=lambda: set_custom()).props(
                    "unelevated no-caps size=sm color=dark"
                ).mark("button_set_speakers")
            error = ui.label(CUSTOM_ERROR).classes("px-3.5 pb-2 text-xs text-red-700")
            error.set_visibility(False)

    def set_custom():
        count = custom_count(number.value)
        error.set_visibility(count is None)
        if count is None:
            return
        select.set_options(options_with(count), value=count)
        number.value = None
        select.run_method("hidePopup")

    number.on("keydown.enter", set_custom)
    number.on_value_change(lambda: error.set_visibility(False))
    select.on_value_change(lambda e: state.update(speaker_settings(e.value)))

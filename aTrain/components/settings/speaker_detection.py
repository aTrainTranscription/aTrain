from nicegui import app, ui


def input_speaker_detection():
    with ui.column().classes("gap-2"):
        ui.label("Speaker Detection").classes("font-bold text-dark text-md")
        ui.separator()
        input = ui.switch("Speaker Detection").mark("switch_speaker_detection")
        input.props("color=dark")
    input.bind_value(app.storage.general, "speaker_detection")

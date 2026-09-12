# From globals, not cli: cli imports transcribe and with it torch, which
# must stay unloaded until the splash screen fetches it in the background.
from aTrain_core.globals import DEFAULT_CPU_THREADS, MAX_CPU_THREADS
from aTrain_core.settings import ComputeType
from nicegui import ElementFilter, app, ui


def advanced_settings(open: bool):
    with ui.dialog(value=open) as dialog, ui.card() as card:
        dialog.props("position=right full-height").classes("[&>*]:p-0")
        card.props("square").classes("w-72 xl:w-96 p-6 gap-6")
        ui.label("Advanced Settings").classes("text-lg text-dark font-bold")
        input_gpu()
        input_compute_type()
        input_cpu_threads()
        input_temperature()
        input_initial_prompt()
        btn = ui.button("Ok", color="dark").props("unelevated no-caps")
        btn.on_click(dialog.close)
        dialog.on("hide", dialog.delete)


def input_gpu():
    from torch import cuda  # Lazy import for improved startup speed

    state = app.storage.general
    tooltip = "GPU acceleration is only available on cuda-enabled NVIDIA GPUs"
    with ui.column().classes("w-full gap-2"):
        with ui.row(align_items="center").classes("w-full justify-between"):
            ui.label("GPU acceleration").classes("font-bold text-dark")
            ui.icon("info_outline", size="sm", color="grey").tooltip(tooltip)
        ui.separator()
        if cuda.is_available():
            switch = ui.switch("GPU", value=True).props("color=dark")
        else:
            switch = ui.switch("GPU", value=False).props("color=dark disable")
            state["GPU"] = False
        switch.mark("switch_gpu")
    switch.bind_value(state, "GPU")
    switch.on_value_change(set_compute_options)


def input_compute_type():
    state = app.storage.general
    tooltip = "Int8 is the only option on CPU"
    with ui.column().classes("w-full gap-2"):
        with ui.row(align_items="center").classes("w-full justify-between"):
            ui.label("Compute Type").classes("font-bold text-dark")
            ui.icon("info_outline", size="sm", color="grey").tooltip(tooltip)
        ui.separator()
        value = state.get("compute_type") or ComputeType.INT8.value
        select = ui.select(options=[x.value for x in ComputeType], value=value)
        select.props("filled bg-color=gray-100 color=dark").classes("w-full")
        select.bind_value(state, "compute_type").mark("select_compute")
    set_compute_options()


def input_cpu_threads():
    state = app.storage.general
    tooltip = f"Number of CPU threads to use (default: {DEFAULT_CPU_THREADS}). Only applies when using CPU."

    with ui.column().classes("w-full gap-2"):
        with ui.row(align_items="center").classes("w-full justify-between"):
            ui.label("CPU Threads").classes("font-bold text-dark")
            ui.icon("info_outline", size="sm", color="grey").tooltip(tooltip)
        ui.separator()

        with ui.row().classes("w-full gap-2 items-center"):
            number = ui.number(
                min=1,
                max=MAX_CPU_THREADS,
                step=1,
                precision=0,
                value=state.get("cpu_threads", DEFAULT_CPU_THREADS),
            )
            number.props("filled bg-color=gray-100 color=dark").classes("flex-grow")
            number.bind_value(state, "cpu_threads").mark("number_cpu_threads")
            reset_btn = ui.button(icon="refresh", color="gray-300").mark("button_reset_cpu_threads")
            reset_btn.props("flat dense round size=sm").tooltip("Reset to default")
            reset_btn.on_click(lambda: number.set_value(DEFAULT_CPU_THREADS))


def input_temperature():
    tooltip = "Increasing temperature (ranges from 0 to 1) results in more varied output, 0 is deterministic. Only change when the default when you have repetition loops or other issues with transcription."

    with ui.column().classes("w-full gap-2"):
        with ui.row(align_items="center").classes("w-full justify-between"):
            ui.label("Temperature").classes("font-bold text-dark")
            ui.icon("info_outline", size="sm", color="grey").tooltip(tooltip)
        ui.separator()
        with ui.row().classes("w-full gap-2 items-center"):
            number = ui.number(min=0.0, max=1.0, step=0.1, precision=1, placeholder="auto")
            number.props("filled bg-color=gray-100 color=dark").classes("flex-grow")
            number.bind_value(app.storage.general, "temperature_override").mark(
                "number_temperature"
            )  # <- New state name

            reset_btn = ui.button(icon="refresh", color="gray-300").mark("button_reset_temperature")
            reset_btn.props("flat dense round size=sm").tooltip("Reset to default (auto)")
            reset_btn.on_click(lambda: number.set_value(None))

    # Fix wrong default setting from version 1.4.0, TODO: Revert state name to "temperature" in upcoming releases
    app.storage.general["temperature"] = None


def input_initial_prompt():
    tooltip = "Use a prompt to influence the output. Usefull for giving names or special technical or domain vocabulary. Allows also to specify style of punctuation."

    with ui.column().classes("w-full gap-2"):
        with ui.row(align_items="center").classes("w-full justify-between"):
            ui.label("Initial Prompt").classes("font-bold text-dark")
            ui.icon("info_outline", size="sm", color="grey").tooltip(tooltip)
        ui.separator()
        textarea = ui.textarea(placeholder="Type here...").mark("textarea_initial_prompt")
        textarea.props("color=dark autogrow clearable").classes("w-full")
    textarea.bind_value(app.storage.general, "initial_prompt")


def set_compute_options():
    state = app.storage.general
    options = list(map(str, ComputeType)) if state["GPU"] else [ComputeType.INT8.value]
    new_value = ComputeType.INT8.value if not state["GPU"] else state["compute_type"]
    for select in ElementFilter(marker="select_compute", kind=ui.select):
        select.set_options(options, value=new_value)

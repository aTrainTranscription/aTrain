"""The running job and a queue summary, shown on the transcribe page."""

from datetime import datetime

from aTrain.components.queue_view import RUNNING, confirm
from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.jobs import FINAL_STATUSES, JobStatus
from nicegui import ui

ACTIVE = RUNNING | {JobStatus.TRANSCRIBED}  # transcribed: speaker detection starts right away


def elapsed(started_at: str | None) -> str:
    if not started_at:
        return ""
    s = int((datetime.now() - datetime.strptime(started_at, TIMESTAMP_FORMAT)).total_seconds())
    return f"{s // 3600:02}:{s % 3600 // 60:02}:{s % 60:02}"


def queue_status(service, start_button) -> None:
    """Hidden while no job is open; updated twice a second. `start_button` says "Start" for
    the first job and "Add to queue" while jobs are open."""
    with ui.card().props("flat").classes("w-full bg-gray-100 rounded-lg px-5 py-4 gap-3") as card:
        with ui.row().classes("w-full justify-between items-baseline no-wrap"):
            with ui.row().classes("gap-2 items-baseline no-wrap min-w-0"):
                step = ui.label().classes("font-bold text-dark")
                task = ui.label()
                file = ui.label().classes("text-sm text-gray-500 truncate")
            percent = ui.label().classes("font-medium")
        bar = ui.linear_progress(show_value=False, color="dark").props(
            "rounded size=6px track-color=grey-4 animation-speed=500"
        )
        with ui.row().classes("w-full justify-between items-center text-sm text-gray-600"):
            with ui.row().classes("gap-4"):
                device = ui.label()
                time = ui.label()
            with ui.row().classes("gap-4 items-center"):
                summary = ui.label()
                ui.link("View queue", "/queue").classes("text-dark font-medium no-underline")
                stop = ui.button("Stop", color="white").props(
                    "unelevated no-caps size=sm text-color=dark"
                )
    card.mark("queue_status")

    current = {"id": None}

    def confirm_stop():
        job_id = current["id"]
        if job_id is not None:
            confirm("Stop the current job?", lambda: service.cancel([job_id]), lambda: None)

    stop.on_click(confirm_stop)

    def update():
        jobs = service.jobs()
        open_jobs = [(spec, state) for spec, state in jobs if state.status not in FINAL_STATUSES]
        card.set_visibility(bool(open_jobs))
        label = "Add to queue" if open_jobs else "Start"
        if start_button.text != label:
            start_button.text = label
        if not open_jobs:
            return
        running = next(((sp, st) for sp, st in open_jobs if st.status in ACTIVE), None)
        finished = len(jobs) - len(open_jobs)
        waiting = len(open_jobs) - (1 if running else 0)
        summary.text = f"Job {finished + 1} of {len(jobs)} · {waiting} waiting"

        if running is None:
            current["id"] = None
            step.text = "Paused" if service.paused else "Waiting"
            for label in (task, file, device, time, percent):
                label.text = ""
            bar.value = 0
            stop.set_visibility(False)
            return

        spec, state = running
        status = state.status
        current["id"] = spec.id
        steps = 2 if spec.speaker_detection else 1
        step.text = f"Step {1 if status == JobStatus.TRANSCRIBING else 2}/{steps}:"
        if state.cancelling:
            task.text = "Cancelling…"
        else:
            task.text = "Transcribing" if status == JobStatus.TRANSCRIBING else "Detecting speakers"
        file.text = spec.display_name
        progress = 0.0 if status == JobStatus.TRANSCRIBED else state.progress
        percent.text, bar.value = f"{int(progress * 100)}%", progress
        device.text = f"Running on {spec.device.value.upper()}"
        time.text = f"Time: {elapsed(state.started_at)}"
        stop.set_visibility(not state.cancelling)

    update()
    ui.timer(0.5, update)

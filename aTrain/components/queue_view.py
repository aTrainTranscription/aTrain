"""The queue list with its buttons, shown on the Queue tab."""

import inspect

from aTrain.components.dialogs.error import dialog_error
from aTrain.utils.archive import download_file_directory, open_file_directory
from aTrain_core.jobs import FINAL_STATUSES, JobStatus
from nicegui import app, ui

STATUS_TEXT = {
    JobStatus.QUEUED: "Queued",
    JobStatus.TRANSCRIBING: "Transcribing",
    JobStatus.TRANSCRIBED: "Waiting for speaker detection",
    JobStatus.DIARIZING: "Detecting speakers",
    JobStatus.DONE: "Done",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
}
RUNNING = {JobStatus.TRANSCRIBING, JobStatus.DIARIZING}
WAITING = {JobStatus.QUEUED, JobStatus.TRANSCRIBED}
COLUMNS = "minmax(0, 2fr) minmax(0, 2fr) minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1.2fr)"


def queue_view(service) -> None:
    """Toolbar and job list, updated twice a second while the page is open."""
    progress_bars: dict = {}

    @ui.refreshable
    def job_list():
        progress_bars.clear()
        jobs = service.jobs()
        if not jobs:
            ui.label("The queue is empty.").classes("text-gray-500")
            return
        with ui.list().classes("w-full").props("separator"):
            with ui.item(), ui.grid(columns=COLUMNS).classes("w-full text-grey text-xs"):
                for title in ("File", "Settings", "Status", "Progress", "Actions"):
                    ui.label(title)
            for spec, state in jobs:
                job_row(service, spec, state, progress_bars, job_list.refresh)

    with ui.row().classes("justify-between w-full items-center"):
        ui.label("Queue").classes("text-lg text-dark font-bold")
        with ui.row():
            pause = ui.button(color="dark").props("size=0.8rem unelevated no-caps")
            pause.on_click(lambda: service.resume() if service.paused else service.pause())
            cancel_all = ui.button("Cancel all", color="gray-100")
            cancel_all.props("size=0.8rem unelevated no-caps")
            cancel_all.on_click(lambda: confirm_cancel_all(service, job_list.refresh))
            clear = ui.button("Clear finished", color="gray-100")
            clear.props("size=0.8rem unelevated no-caps")
            clear.on_click(lambda: confirm_clear_finished(service, job_list.refresh))

    job_list()
    last_signature = None

    def update():
        nonlocal last_signature
        jobs = service.jobs()
        pause.text = "Resume" if service.paused else "Pause"
        cancel_all.set_enabled(any(state.status not in FINAL_STATUSES for _, state in jobs))
        clear.set_enabled(any(state.status in FINAL_STATUSES for _, state in jobs))
        signature = [
            (spec.id, state.status, state.cancelling, tuple(state.warnings)) for spec, state in jobs
        ]
        if signature != last_signature:
            last_signature = signature
            job_list.refresh()
        for spec, state in jobs:
            if spec.id in progress_bars:
                progress_bars[spec.id].value = state.progress

    update()
    ui.timer(0.5, update)


def job_row(service, spec, state, progress_bars: dict, refresh) -> None:
    status = state.status
    with ui.item().classes("hover:bg-gray-100"):
        with ui.grid(columns=COLUMNS).classes("w-full items-center"):
            ui.label(spec.display_name).classes("font-light truncate")
            with ui.label(settings_summary(spec)).classes("font-light truncate"):
                ui.tooltip(settings_details(spec)).classes("whitespace-pre-line")
            status_label(state, status)
            bar = ui.linear_progress(value=state.progress, show_value=False, color="dark")
            if status not in RUNNING:
                bar.classes("invisible")  # keeps its grid cell, so Actions stay in their column
            progress_bars[spec.id] = bar
            with ui.row().classes("gap-1 items-center"):
                if status == JobStatus.DONE:
                    native = app.native.main_window is not None
                    action_button(
                        "open" if native else "download", lambda: open_result(state.file_id)
                    )
                if status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    action_button("retry", lambda: (service.retry(spec.id), refresh()))
                if status in WAITING:
                    action_button("↑", lambda: (service.move(spec.id, -1), refresh()))
                    action_button("↓", lambda: (service.move(spec.id, 1), refresh()))
                if not state.cancelling:
                    action_button("✕", lambda: confirm_remove(service, spec, status, refresh))


def status_label(state, status: JobStatus) -> None:
    text = "Cancelling…" if state.cancelling else STATUS_TEXT.get(status, status)
    if status == JobStatus.DONE and state.warnings:
        ui.button(
            "Done with warnings",
            icon="warning",
            color="amber-900",
            on_click=lambda: show_warnings(state.warnings),
        ).props("flat dense no-caps")
        return
    if status != JobStatus.FAILED:
        ui.label(text).classes("font-light")
        return
    label = ui.label(f"{text} ⓘ").classes("font-light text-red-700 cursor-pointer")
    with label:
        ui.tooltip(f"{state.failed_step or ''}: {state.error or ''}")
    label.on(
        "click", lambda: dialog_error(error=state.error or "", traceback=state.traceback or "")
    )


def show_warnings(warnings: list[str]) -> None:
    with ui.dialog(value=True) as dialog, ui.card().classes("p-6 gap-4"):
        ui.label("Transcription completed").classes("font-bold text-dark")
        ui.label("The transcript is available in the archive.")
        for warning in warnings:
            ui.label(warning).classes("whitespace-pre-line break-all")
        ui.button("Close", color="dark", on_click=dialog.close).props("unelevated no-caps")


def action_button(text: str, on_click) -> None:
    button = ui.button(text, color="gray-100", on_click=on_click)
    button.props("no-caps size=0.7rem unelevated")


def open_result(file_id: str) -> None:
    if app.native.main_window is None:
        download_file_directory(file_id)
    else:
        open_file_directory(file_id)


def settings_summary(spec) -> str:
    if not spec.speaker_detection:
        speakers = "no speakers"
    else:
        speakers = f"{spec.speaker_count} speakers" if spec.speaker_count else "speakers: auto"
    return f"{spec.model} · {spec.language} · {speakers} · {spec.device.value.upper()}"


def settings_details(spec) -> str:
    lines = [
        f"Model: {spec.model}",
        f"Language: {spec.language}",
        f"Speaker detection: {'yes' if spec.speaker_detection else 'no'}",
        f"Number of speakers: {spec.speaker_count or 'auto'}",
        f"Device: {spec.device.value.upper()}",
        f"Compute type: {spec.compute_type.value}",
        f"Temperature: {'default' if spec.temperature is None else spec.temperature}",
        f"Initial prompt: {spec.initial_prompt or '-'}",
    ]
    if spec.export_dir:
        lines.append(f"Copy to: {spec.export_dir}")
    return "\n".join(lines)


def confirm(text: str, action, refresh) -> None:
    with ui.dialog(value=True) as dialog, ui.card().classes("p-6 gap-4"):
        ui.label(text).classes("whitespace-pre-line")
        with ui.row().classes("w-full justify-end"):
            ui.button("Back", color="gray-100", on_click=dialog.close).props("no-caps unelevated")

            async def ok():
                dialog.close()
                result = action()
                if inspect.isawaitable(result):
                    await result
                refresh()

            ui.button("OK", color="dark", on_click=ok).props("no-caps unelevated").mark(
                "confirm_ok"
            )


def confirm_remove(service, spec, status: JobStatus, refresh) -> None:
    name = spec.display_name
    if status in RUNNING:
        confirm(f"Stop transcribing {name}?", lambda: service.cancel([spec.id]), refresh)
        return
    text = f"Remove {name} from the queue?"
    if status == JobStatus.DONE:
        text = f"Remove {name}? The transcript stays in the archive."
    if (service.store.uploads_root / spec.id).exists():
        text += "\nThe uploaded file will be deleted."
    confirm(text, lambda: service.remove(spec.id), refresh)


def confirm_cancel_all(service, refresh) -> None:
    ids = [spec.id for spec, state in service.jobs() if state.status not in FINAL_STATUSES]
    confirm(f"Stop all {len(ids)} unfinished jobs?", lambda: service.cancel(ids), refresh)


def confirm_clear_finished(service, refresh) -> None:
    finished = [spec for spec, state in service.jobs() if state.status in FINAL_STATUSES]
    uploads = sum((service.store.uploads_root / spec.id).exists() for spec in finished)
    text = f"Remove {len(finished)} finished, failed or cancelled jobs from the queue?"
    if uploads:
        text += f"\nThis also deletes the uploaded files of {uploads} failed or cancelled jobs."
    confirm(text, service.clear_finished, refresh)

"""The queue on the transcribe page: the running job, the controls and the list of all
other jobs with their actions."""

import inspect
from datetime import datetime

from aTrain.components.dialogs.error import dialog_error
from aTrain.utils.archive import download_file_directory, open_file_directory
from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.jobs import FINAL_STATUSES, JobStatus, Step
from nicegui import app, ui

STATUS_TEXT = {
    JobStatus.QUEUED: "Queued",
    JobStatus.RUNNING: "Running",
    JobStatus.DONE: "Done",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
}
ICONS = {
    JobStatus.QUEUED: ("schedule", "text-gray-400"),
    JobStatus.DONE: ("check_circle", "text-dark"),
    JobStatus.FAILED: ("error", "text-red-700"),
    JobStatus.CANCELLED: ("block", "text-dark"),
}
WHITE = 'unelevated no-caps size=13px padding="6px 12px" color=white text-color=dark'
ROW_BUTTON = "flat round dense size=sm color=dark"


def elapsed(started_at: str | None) -> str:
    if not started_at:
        return ""
    s = int((datetime.now() - datetime.strptime(started_at, TIMESTAMP_FORMAT)).total_seconds())
    return f"{s // 3600:02}:{s % 3600 // 60:02}:{s % 60:02}"


def running_job(jobs):
    """The job in the header."""
    return next((job for job in jobs if job[1].status == JobStatus.RUNNING), None)


def summary_text(jobs) -> str:
    counts = {"waiting": 0, "done": 0, "failed": 0, "cancelled": 0}
    for _, state in jobs:
        if state.status == JobStatus.QUEUED:
            counts["waiting"] += 1
        elif state.status in FINAL_STATUSES:
            counts[state.status.value] += 1
    return " · ".join(["Queue", *(f"{n} {name}" for name, n in counts.items() if n)])


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def queue_status(service):
    """Hidden while the queue is empty; updated twice a second. Returns a function that
    opens the job list."""
    separator = ui.separator()
    with ui.column().classes("w-full bg-gray-100 rounded-lg px-6 py-5 gap-3.5") as panel:
        with ui.column().classes("w-full gap-3.5") as header:
            with ui.row().classes("w-full justify-between items-end gap-6 no-wrap"):
                with ui.column().classes("gap-1 min-w-0"):
                    name = ui.label().classes("text-[15px] font-medium truncate max-w-full")
                    details = ui.label().classes("text-[13px] text-gray-600 tabular-nums")
                percent = ui.label().classes("text-xl font-medium tabular-nums")
            bar = ui.linear_progress(show_value=False, color="dark").props(
                "rounded size=6px track-color=grey-4 animation-speed=500"
            )
        with ui.row().classes("items-center gap-2.5") as idle:
            idle_icon = ui.icon("check_circle").classes("text-xl")
            idle_text = ui.label().classes("text-[15px] font-medium")
        with ui.row().classes("w-full justify-between items-center"):
            summary = ui.button(on_click=lambda: toggle_list()).props(
                f"{WHITE} icon-right=expand_less"
            )
            with ui.row().classes("gap-2"):
                pause = ui.button(
                    on_click=lambda: service.resume() if service.paused else service.pause()
                ).props(WHITE)
                stop = ui.button("Stop", on_click=lambda: ask_stop()).props(WHITE)
                stop_all = ui.button("Stop all", on_click=lambda: ask_stop_all()).props(
                    'unelevated no-caps size=13px padding="6px 12px" color=dark'
                )
        summary.mark("queue_summary")
        pause.mark("pause_queue")
        stop.mark("stop_job")
        stop_all.mark("stop_all")
        with ui.row().classes(
            "w-full justify-between items-center gap-4 no-wrap bg-white rounded-md px-3.5 py-2.5"
        ) as confirm_bar:
            confirm_text = ui.label().classes("text-sm whitespace-pre-line")
            with ui.row().classes("gap-2 no-wrap"):
                ui.button("Back", on_click=lambda: close_confirm()).props(
                    'unelevated no-caps size=13px padding="6px 12px" color=gray-100 text-color=dark'
                )
                confirm_ok = ui.button(on_click=lambda: do_confirm()).props(
                    'unelevated no-caps size=13px padding="6px 12px" color=dark'
                )
                confirm_ok.mark("confirm_ok")
        job_list_box = ui.column().classes("w-full bg-white rounded-md gap-0 -mt-1")
    panel.mark("queue_status")
    confirm_bar.set_visibility(False)

    # --- confirmation bar ---------------------------------------------------------------

    pending = {"action": None}

    def ask(text: str, ok: str, action) -> None:
        pending["action"] = action
        confirm_text.text, confirm_ok.text = text, ok
        confirm_bar.set_visibility(True)

    def close_confirm() -> None:
        pending["action"] = None
        confirm_bar.set_visibility(False)

    async def do_confirm() -> None:
        action = pending["action"]
        close_confirm()
        if action is None:
            return
        try:
            result = action()
            if inspect.isawaitable(result):
                await result
        except KeyError:
            pass  # the job was removed meanwhile
        job_list.refresh()

    def ask_stop() -> None:
        jobs = service.jobs()
        running = running_job(jobs)
        if running is not None:
            spec = running[0]
            ask(
                f"Stop transcribing {spec.display_name}?",
                "Stop job",
                lambda: service.cancel([spec.id]),
            )

    def ask_stop_all() -> None:
        ids = [spec.id for spec, state in service.jobs() if state.status not in FINAL_STATUSES]
        ask(f"Stop all {len(ids)} unfinished jobs?", "Stop all", lambda: service.cancel(ids))

    def ask_remove(spec, status: JobStatus) -> None:
        name = spec.display_name
        if status == JobStatus.DONE:
            text = f"Remove {name}? The transcript stays in the archive."
        else:
            text = f"Remove {name} from the queue?"
        if (service.store.uploads_root / spec.id).exists():
            text += "\nThe uploaded file will be deleted."
        ask(text, "Remove", lambda: service.remove(spec.id))

    def ask_clear_finished() -> None:
        finished = [spec for spec, state in service.jobs() if state.status in FINAL_STATUSES]
        uploads = sum((service.store.uploads_root / spec.id).exists() for spec in finished)
        text = (
            f"Remove {plural(len(finished), 'finished, failed or cancelled job')} from the queue?"
        )
        if uploads:
            jobs = plural(uploads, "failed or cancelled job")
            text += f"\nThis also deletes the uploaded files of {jobs}."
        ask(text, "Clear", service.clear_finished)

    # --- job list -----------------------------------------------------------------------

    def toggle_list() -> None:
        job_list_box.set_visibility(not job_list_box.visible)
        summary.props(f"icon-right={'expand_less' if job_list_box.visible else 'expand_more'}")

    def open_list() -> None:
        if not job_list_box.visible:
            toggle_list()

    def retry(job_id: str) -> None:
        service.retry(job_id)
        job_list.refresh()

    def move(job_id: str, delta: int) -> None:
        service.move(job_id, delta)
        job_list.refresh()

    def show_error(spec, state) -> None:
        with panel:  # not in the list, so a refresh of the list keeps the dialog
            dialog_error(
                error=state.error or "",
                traceback=state.traceback or "",
                on_retry=lambda: retry(spec.id),
            )

    def show_warnings(warnings: list[str]) -> None:
        with panel, ui.dialog(value=True) as dialog, ui.card().classes("p-6 gap-4"):
            ui.label("Transcription completed").classes("font-bold text-dark")
            ui.label("The transcript is available in the archive.")
            for warning in warnings:
                ui.label(warning).classes("whitespace-pre-line break-all")
            ui.button("Close", color="dark", on_click=dialog.close).props("unelevated no-caps")

    last_signature = None

    def signature(jobs):
        return [(spec.id, state.status, bool(state.warnings)) for spec, state in jobs]

    @ui.refreshable
    def job_list() -> None:
        nonlocal last_signature
        jobs = service.jobs()
        last_signature = signature(jobs)
        running = running_job(jobs)
        rows = [job for job in jobs if job is not running]
        queued = [spec.id for spec, state in rows if state.status == JobStatus.QUEUED]
        for spec, state in rows:
            job_row(spec, state, queued)
        if not rows:
            ui.label("The queue is empty.").classes("px-3.5 py-3 text-[13px] text-gray-500")
        if any(state.status in FINAL_STATUSES for _, state in rows):
            with ui.row().classes("px-3.5 py-2"):
                ui.button("Clear finished", icon="clear_all", on_click=ask_clear_finished).props(
                    'unelevated no-caps size=13px padding="6px 12px" color=gray-100 text-color=dark'
                )

    def job_row(spec, state, queued: list[str]) -> None:
        status = state.status
        icon, color = ICONS[status]
        with (
            ui.grid(columns="20px minmax(0, 1fr) auto 112px")
            .classes("w-full gap-3 items-center px-3.5 py-2.5 border-b border-gray-100 text-[13px]")
            .mark(f"job_{spec.id}")
        ):
            ui.icon(icon).classes(f"text-lg {color}")
            with ui.row().classes("gap-2.5 items-baseline no-wrap min-w-0 cursor-default"):
                ui.label(spec.display_name).classes("text-sm truncate flex-none max-w-[55%]")
                ui.label(settings_summary(spec)).classes("text-gray-500 truncate")
                ui.tooltip(settings_details(spec)).classes("whitespace-pre-line")
            if status == JobStatus.FAILED:
                failed = ui.label("Failed ⓘ").classes("text-red-700 cursor-pointer")
                with failed:
                    ui.tooltip(f"{state.failed_step or ''}: {state.error or ''}")
                failed.on("click", lambda: show_error(spec, state))
            elif status == JobStatus.DONE and state.warnings:
                ui.button(
                    "Done with warnings",
                    icon="warning",
                    color="amber-900",
                    on_click=lambda: show_warnings(state.warnings),
                ).props("flat dense no-caps size=sm")
            else:
                ui.label(STATUS_TEXT[status]).classes("text-gray-600")
            with ui.row().classes("gap-0.5 justify-end no-wrap"):
                if status == JobStatus.DONE:
                    native = app.native.main_window is not None
                    ui.button(
                        icon="folder_open" if native else "download",
                        on_click=lambda: open_result(state.file_id),
                    ).props(ROW_BUTTON).tooltip("Open result folder" if native else "Download")
                if status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    ui.button(icon="replay", on_click=lambda: retry(spec.id)).props(
                        ROW_BUTTON
                    ).tooltip("Retry")
                if status == JobStatus.QUEUED:
                    index = queued.index(spec.id)
                    up = ui.button(icon="arrow_upward", on_click=lambda: move(spec.id, -1))
                    down = ui.button(icon="arrow_downward", on_click=lambda: move(spec.id, 1))
                    up.props(ROW_BUTTON).tooltip("Move up").set_enabled(index > 0)
                    down.props(ROW_BUTTON).tooltip("Move down")
                    down.set_enabled(index < len(queued) - 1)
                ui.button(icon="close", on_click=lambda: ask_remove(spec, status)).props(
                    ROW_BUTTON
                ).tooltip("Remove")

    with job_list_box:
        job_list()

    # --- polling ------------------------------------------------------------------------

    def update() -> None:
        jobs = service.jobs()
        separator.set_visibility(bool(jobs))
        panel.set_visibility(bool(jobs))
        if not jobs:
            return
        if signature(jobs) != last_signature:
            job_list.refresh()
        open_jobs = [job for job in jobs if job[1].status not in FINAL_STATUSES]
        running = running_job(jobs)
        waiting = sum(state.status == JobStatus.QUEUED for _, state in jobs)
        summary.text = summary_text(jobs)
        pause.text = "Resume" if service.paused else "Pause"
        pause.set_visibility(bool(open_jobs))
        stop_all.set_visibility(len(open_jobs) > 1)
        header.set_visibility(running is not None)
        idle.set_visibility(running is None)

        if running is None:
            stop.set_visibility(False)
            if waiting and service.paused:
                idle_icon.name, idle_text.text = "pause_circle", f"Paused · {waiting} waiting"
            elif waiting:
                idle_icon.name, idle_text.text = "schedule", f"Starting · {waiting} waiting"
            else:
                idle_icon.name, idle_text.text = "check_circle", "All jobs finished"
            return

        spec, state = running
        diarizing = service.step == Step.DIARIZATION
        steps = 2 if spec.speaker_detection else 1
        step = 2 if diarizing else 1
        if state.cancelling:
            task = "Cancelling…"
        else:
            task = "Detecting speakers" if diarizing else "Transcribing"
        progress = min(state.progress, 1.0)
        name.text = spec.display_name
        details.text = " · ".join(
            filter(
                None,
                [
                    task,
                    f"Step {step} of {steps}",
                    spec.device.value.upper(),
                    elapsed(state.started_at),
                ],
            )
        )
        percent.text, bar.value = f"{int(progress * 100)}%", progress
        stop.set_visibility(not state.cancelling)

    update()
    ui.timer(0.5, update)
    return open_list


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
    language = "auto" if spec.language == "auto-detect" else spec.language
    return f"{spec.model} · {language} · {speakers} · {spec.device.value.upper()}"


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

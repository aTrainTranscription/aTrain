import os
from pathlib import Path

from aTrain.utils.file_selection import FileSelection
from aTrain_core.globals import FLATPAK, LINUX
from aTrain_core.settings import load_formats
from nicegui import app, ui

# Swapped in the browser while files are dragged over the drop zone (no server round trip).
IDLE = "'border-gray-300', 'bg-gray-50'"
DRAGGING = "'border-gray-800', 'bg-gray-100'"
DRAG_OVER = (
    f"(e) => {{ e.preventDefault(); const c = e.currentTarget.classList; "
    f"c.remove({IDLE}); c.add({DRAGGING}); }}"
)
DRAG_END = f"const c = e.currentTarget.classList; c.remove({DRAGGING}); c.add({IDLE});"


def input_file(on_change) -> FileSelection:
    """The drop zone: drop or browse files, or (in a native window) pick a folder.
    `on_change` runs whenever the selection changes."""
    allowed_files = "".join(x for x in str(load_formats()) if x not in "[]'")
    uploader = ui.upload(multiple=True, auto_upload=True).classes("hidden")
    uploader.props(f"accept='{allowed_files}' batch")
    native = app.native.main_window is not None
    portal = (FLATPAK or LINUX) and native
    selection = FileSelection(uploader, native, portal)
    qref = f"getElement({uploader.id}).$refs.qRef"
    uploader.on_rejected(lambda: ui.notify("Only audio and video files can be added"))
    uploader.on_begin_upload(selection.upload_started)
    uploader.on_multi_upload(selection.uploaded)
    # sent: the uploader forgets them, so the same file can be added again
    uploader.on("uploaded", js_handler=f"() => {qref}.removeUploadedFiles()")
    uploader.on("failed", selection.upload_failed, args=[])

    zone = ui.element("div").classes(
        "w-full min-h-[260px] flex flex-col rounded-lg border-[1.5px] border-dashed "
        "border-gray-300 bg-gray-50 transition-colors"
    )
    zone.on("dragover", js_handler=DRAG_OVER)
    zone.on(
        "dragleave",
        js_handler=f"(e) => {{ if (e.currentTarget.contains(e.relatedTarget)) return; {DRAG_END} }}",
    )
    # A browser hands over the files. WebKitGTK (Linux window) doesn't: there the window
    # process sends their paths (aTrain.utils.linux_drop), read like picked files.
    zone.on(
        "drop",
        js_handler=f"(e) => {{ e.preventDefault(); {DRAG_END} "
        f"if (e.dataTransfer.files.length) {qref}.addFiles(e.dataTransfer.files); }}",
    )
    if portal:
        from aTrain.utils.linux_drop import EVENT

        ui.on(EVENT, selection.add_dropped)
    zone.mark("drop_zone")

    @ui.refreshable
    def content():
        names = selection.names
        if not names and not selection.uploading:
            empty_state(native, selection)
            return
        with ui.column().classes("flex-1 w-full p-3 gap-1.5 no-wrap"):
            with ui.row().classes("w-full justify-between items-center px-2 pb-1.5"):
                count = f"{len(names)} file{'s' if len(names) != 1 else ''} selected"
                count = count if names else "Uploading…"
                ui.label(count).classes("text-[13px] font-medium text-gray-600")
                if not selection.uploading:
                    clear = ui.label("Clear").classes(
                        "text-[13px] text-grey underline cursor-pointer"
                    )
                    clear.on("click", selection.clear)
            with ui.column().classes("w-full gap-1.5 no-wrap max-h-[320px] overflow-auto"):
                for index, name in enumerate(names):
                    with ui.row().classes(
                        "w-full items-center gap-2.5 no-wrap bg-white rounded-md px-2.5 py-1.5 text-sm"
                    ):
                        ui.icon("audio_file", color="grey").classes("text-lg")
                        ui.label(name).classes("flex-1 min-w-0 truncate")
                        if not selection.uploading:
                            ui.button(
                                icon="close", on_click=lambda i=index: selection.remove(i)
                            ).props("flat round dense size=sm color=grey")
            if selection.uploading:
                if names:
                    ui.label("Uploading…").classes("px-2 pt-1 text-[13px] text-gray-600")
                return
            if selection.folder is not None:
                folder_options(selection, selection.folder)
            more = ui.button("Add more files", icon="add", on_click=selection.browse_files)
            more.props("flat no-caps color=grey-8").classes("w-full mt-1")

    def changed():
        content.refresh()
        on_change()

    selection.on_change = changed
    with zone:
        content()
    return selection


def empty_state(native: bool, selection: FileSelection) -> None:
    with ui.column().classes(
        "flex-1 w-full items-center justify-center gap-2.5 p-8 text-center cursor-pointer"
    ) as empty:
        ui.icon("upload_file", color="grey").classes("text-[36px]")
        ui.label("Drop audio or video files").classes("text-[15px] font-medium")
        with ui.row().classes("gap-1 justify-center text-[13px] text-grey"):
            ui.label("or")
            ui.label("browse").classes("font-medium text-dark underline")
            if native:
                ui.label("· files or a whole")
                folder = ui.label("folder").classes("font-medium text-dark underline")
                folder.on("click.stop", selection.browse_folder)
            else:
                ui.label("· one or more files")
    empty.on("click", selection.browse_files)


def folder_options(selection: FileSelection, folder: Path) -> None:
    ignored = selection.ignored
    if ignored:
        note = f"{ignored} other file{'s' if ignored != 1 else ''} in the folder ignored"
        ui.label(note).classes("px-2 pt-1 text-[13px] text-gray-600")
    export = ui.checkbox("Also save a copy next to the source files", value=selection.export)
    export.classes("text-sm").bind_value_to(selection, "export")
    if not os.access(folder, os.W_OK):
        export.disable()
        ui.label("This folder is read-only: a copy next to the files is not possible.").classes(
            "px-2 text-[13px] text-gray-600"
        )

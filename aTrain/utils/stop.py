from concurrent.futures import ThreadPoolExecutor

from nicegui import run


def stop_run() -> None:
    """Kill the running transcription or download and keep NiceGUI usable.

    `run.tear_down` also shuts down `run.thread_pool`, and NiceGUI only rebuilds the
    process pool. A dead thread pool makes every later `run.io_bound` call (file
    uploads, the native file dialog) return None on NiceGUI 3 and raise
    `CancelledError` on NiceGUI 4, so the thread pool is rebuilt here.
    """
    run.tear_down()
    run.thread_pool = ThreadPoolExecutor()

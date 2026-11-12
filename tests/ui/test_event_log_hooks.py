"""Which events `aTrain start` logs (#339).

No server and no worker runs, but aTrain/app.py imports nicegui in start(), so
these live in tests/ui. log_event is replaced by a recorder, ui.run and the wake
lock by stubs.
"""

import contextlib
import sys
from unittest.mock import Mock

import aTrain.app as atrain_cli
import nicegui.error
import pytest
from aTrain.version import __version__
from nicegui import app, run, ui
from wakepy import keep


def _recorder(recorded):
    def record(event, level=None, **fields):
        recorded.append((event, fields))

    return record


@pytest.fixture
def cli_events(monkeypatch):
    """`aTrain start` without a log file, a server or a wake lock."""
    recorded = []
    monkeypatch.setattr(atrain_cli, "setup_event_log", Mock())
    monkeypatch.setattr(atrain_cli, "log_event", _recorder(recorded))
    monkeypatch.setattr(
        atrain_cli,
        "log_unhandled_exception",
        lambda error: recorded.append(("unhandled_exception", {"error": str(error)})),
    )
    # The host check adds a middleware to the global app. The stub keeps it out of
    # the other tests.
    monkeypatch.setattr(atrain_cli, "restrict_to_loopback_hosts", Mock())
    monkeypatch.setattr(app, "on_shutdown", Mock())
    monkeypatch.setattr(app, "on_exception", Mock())
    monkeypatch.setattr(app, "on_page_exception", Mock())
    monkeypatch.setattr(ui, "run", Mock())
    monkeypatch.setattr(keep, "running", contextlib.nullcontext)
    # start() sets the pool's start method; keep that from leaking into other tests.
    monkeypatch.setattr(run, "process_pool_start_method", run.process_pool_start_method)
    # start() imports the page modules. If they stayed in sys.modules, the user tests
    # that follow would reuse them and their routes would be missing (see
    # tests/ui/main.py).
    monkeypatch.setitem(sys.modules, "aTrain.pages", Mock())
    return recorded


def _start(**options):
    defaults = {"native": False, "reload": False, "show": False, "host": None, "port": 8100}
    atrain_cli.start(**{**defaults, **options})


def test_start_logs_the_server_and_registers_the_hooks(cli_events):
    _start()

    assert cli_events == [
        (
            "server_started",
            {
                "version": __version__,
                "native": False,
                "host": "127.0.0.1",
                "port": 8100,
                "allow_any_host": False,
            },
        )
    ]
    atrain_cli.setup_event_log.assert_called_once()
    app.on_exception.assert_called_once_with(atrain_cli.log_unhandled_exception)
    on_stop = app.on_shutdown.call_args.args[0]
    on_stop()
    assert cli_events[-1] == ("server_stopped", {})


def test_start_logs_a_switched_off_host_check(cli_events):
    _start(host="localhost", allow_any_host=True)

    assert cli_events[0][1]["host"] == "localhost"
    assert cli_events[0][1]["allow_any_host"] is True
    atrain_cli.restrict_to_loopback_hosts.assert_not_called()


def test_a_crash_at_startup_is_logged(cli_events, monkeypatch):
    """The Windows build has no console, so the log is the only trace of it."""
    monkeypatch.setattr(ui, "run", Mock(side_effect=RuntimeError("cannot bind")))

    with pytest.raises(RuntimeError):
        _start()

    assert cli_events[-1] == ("unhandled_exception", {"error": "cannot bind"})


def test_a_failed_start_is_logged(cli_events, monkeypatch):
    """uvicorn ends a start on a taken port with sys.exit(1). SystemExit is not an Exception."""
    monkeypatch.setattr(ui, "run", Mock(side_effect=SystemExit(1)))

    with pytest.raises(SystemExit):
        _start()

    assert cli_events[-1] == ("server_failed", {"exit_code": 1})


def test_a_clean_exit_is_not_a_failure(cli_events, monkeypatch):
    monkeypatch.setattr(ui, "run", Mock(side_effect=SystemExit(0)))

    with pytest.raises(SystemExit):
        _start()

    assert "server_failed" not in [event for event, _ in cli_events]


def test_an_error_while_building_a_page_reaches_the_log(cli_events, monkeypatch):
    """Without a page exception handler NiceGUI shows its 500 page and skips the hook."""
    shown = Mock()
    monkeypatch.setattr(nicegui.error, "error_content", shown)
    _start()

    show_error_page = app.on_page_exception.call_args.args[0]
    error = RuntimeError("page failed")
    show_error_page(error)
    shown.assert_called_once_with(500, error)

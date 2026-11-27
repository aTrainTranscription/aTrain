"""Which events `aTrain start` logs (#339).

No server and no worker runs, but aTrain/app.py imports nicegui in start(), so
these live in tests/ui. ui.run and the wake lock are stubs. log_event is replaced
by a recorder, except in the last test, which reads a real log file.
"""

import contextlib
import sys
from logging.handlers import RotatingFileHandler
from unittest.mock import Mock

import aTrain.app as atrain_cli
import nicegui.native
import pytest
from aTrain.version import __version__
from aTrain_core import event_log
from nicegui import app, run, ui
from wakepy import keep


def _recorder(recorded):
    def record(event, level=None, **fields):
        recorded.append((event, fields))

    return record


@pytest.fixture
def no_server(monkeypatch):
    """`aTrain start` without a server or a wake lock."""
    # The host check adds a middleware to the global app. The stub keeps it out of
    # the other tests.
    monkeypatch.setattr(atrain_cli, "restrict_to_loopback_hosts", Mock())
    monkeypatch.setattr(ui, "run", Mock())
    monkeypatch.setattr(keep, "running", contextlib.nullcontext)
    # start() sets the pool's start method; keep that from leaking into other tests.
    monkeypatch.setattr(run, "process_pool_start_method", run.process_pool_start_method)


@pytest.fixture
def cli_events(monkeypatch, no_server):
    """`aTrain start` without a log file and without the hooks on the app."""
    recorded = []
    monkeypatch.setattr(atrain_cli, "setup_event_log", Mock())
    monkeypatch.setattr(atrain_cli, "log_event", _recorder(recorded))
    monkeypatch.setattr(
        atrain_cli,
        "log_unhandled_exception",
        lambda error: recorded.append(("unhandled_exception", {"error": str(error)})),
    )
    monkeypatch.setattr(app, "on_shutdown", Mock())
    monkeypatch.setattr(app, "on_exception", Mock())
    monkeypatch.setattr(app, "on_page_exception", Mock())
    # start() imports the page modules. If they stayed in sys.modules, the user tests
    # that follow would reuse them and their routes would be missing (see
    # tests/ui/main.py).
    monkeypatch.setitem(sys.modules, "aTrain.pages", Mock())
    return recorded


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """`aTrain start` writes its log to a temp folder."""
    monkeypatch.setattr(atrain_cli, "setup_event_log", lambda: event_log.setup_event_log(tmp_path))
    yield tmp_path / event_log.EVENT_LOG_FILENAME
    for handler in list(event_log.logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            event_log.logger.removeHandler(handler)
            handler.close()


def _start(**options):
    defaults = {"native": False, "show": False, "host": None, "port": 8100}
    atrain_cli.start(**{**defaults, **options})


def test_start_logs_the_server_and_registers_the_hooks(cli_events):
    _start()

    assert cli_events == [
        (
            "server_starting",
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


@pytest.mark.parametrize(("native", "picked"), [(False, 8080), (True, 8123)])
def test_start_logs_the_port_it_picks(cli_events, monkeypatch, native, picked):
    """Without --port the log still names the port, the one ui.run would pick."""
    monkeypatch.setattr(nicegui.native, "find_open_port", lambda: 8123)

    _start(native=native, port=None)

    assert cli_events[0][1]["port"] == picked
    assert ui.run.call_args.kwargs["port"] == picked


def test_a_failed_port_search_is_logged(cli_events, monkeypatch):
    def no_port():
        raise OSError("No open port found")

    monkeypatch.setattr(nicegui.native, "find_open_port", no_port)

    with pytest.raises(OSError):
        _start(native=True, port=None)

    assert cli_events == [("unhandled_exception", {"error": "No open port found"})]


def test_a_missing_package_is_logged(cli_events, monkeypatch):
    """The log is set up before the imports, so a build that lacks a package shows it."""
    monkeypatch.setitem(sys.modules, "wakepy", None)

    with pytest.raises(SystemExit, match="GUI extras missing"):
        _start()

    atrain_cli.setup_event_log.assert_called_once()
    assert [event for event, _ in cli_events] == ["unhandled_exception"]


def test_a_crash_while_importing_a_page_is_logged(cli_events, monkeypatch):
    class BrokenPages:
        def __getattr__(self, name):
            raise RuntimeError("broken page")

    monkeypatch.setitem(sys.modules, "aTrain.pages", BrokenPages())

    with pytest.raises(RuntimeError):
        _start()

    assert cli_events == [("unhandled_exception", {"error": "broken page"})]


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


async def test_an_error_while_building_a_page_is_logged_once(user, log_file, no_server, caplog):
    """Without a page exception handler NiceGUI shows its 500 page and skips the hook."""
    _start()

    @ui.page("/broken")
    def broken():
        raise RuntimeError("page failed")

    response = await user.http_client.get("/broken")

    assert response.status_code == 500
    assert "Server error" in response.text
    log = log_file.read_text(encoding="utf-8")
    assert log.count("ERROR unhandled_exception error='page failed'") == 1, log
    caplog.clear()  # the user fixture fails a test that logged an error

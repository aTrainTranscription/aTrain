"""NiceGUI main file for the in-process user-fixture tests.

nicegui>=3 replaced the per-test `module_under_test` marker with a main
file that the `user` fixture executes via runpy for every test (configured
through the `main_file` ini option in pyproject.toml). Importing the page
modules registers their `@ui.page` routes; NiceGUI's own test teardown
pops them from sys.modules afterwards, so each test re-imports them fresh.

Mirrors the page registration in `aTrain.app:start`.

Note for tests that monkeypatch what a page uses: the fresh page import
copies `from`-imported names at import time, so patches must target the
persistent modules (e.g. `aTrain.utils.models`) and be applied before the
`user` fixture runs this file - list the patching fixture before `user`
in the test signature.
"""

from aTrain.pages import about, archive, faq, models, transcribe  # noqa: F401
from nicegui import ui

# Rationale: test-only storage secret for the simulated app, not a credential.
ui.run(storage_secret="test")  # noqa: S106

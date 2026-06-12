from pathlib import Path

import lionscliapp as app
import tkinter as tk
from tkintertester import harness

from . import runtime_tests
from . import ui
from .constants import PROJECT_DIR
from .core import get_lock_path, release_project_lock


def bool_ctx(key):
    value = app.ctx[key]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def app_entry():
    win = tk.Toplevel(harness.g["root"])
    ui.start_in_root(win, app.ctx["execpath.root"], quit_fn=harness.quit)


def cmd_run():
    flags = ""
    if bool_ctx("runtime.tests.show"):
        flags += "s"
    if bool_ctx("runtime.tests.exit"):
        flags += "x"
    if bool_ctx("runtime.tests.enabled"):
        runtime_tests.register_tests()
    harness.run_host(app_entry, flags)


def cmd_unlock():
    execroot = Path(app.ctx["execpath.root"])
    lock_path = get_lock_path(execroot)
    if release_project_lock(execroot, force=True):
        print(f"Deleted lock file: {lock_path}")
    else:
        print(f"No lock file found: {lock_path}")


def main():
    app.declare_app("aspect-slicer", "0.1.0")
    app.describe_app("Exact-aspect image slicer for print workflows.")
    app.declare_projectdir(PROJECT_DIR)
    app.declare_key("execpath.root", str(Path.cwd()))
    app.declare_key("runtime.tests.enabled", False)
    app.declare_key("runtime.tests.show", False)
    app.declare_key("runtime.tests.exit", False)
    app.describe_key("execpath.root", "Folder where .aspect-slicer data is stored.")
    app.describe_key("runtime.tests.enabled", "Register and run GUI tests before normal runtime.")
    app.describe_key("runtime.tests.show", "Show GUI test results in a Tk window.")
    app.describe_key("runtime.tests.exit", "Exit after GUI tests complete.")
    app.declare_cmd("", cmd_run)
    app.describe_cmd("", "Open the Aspect Slicer graphical application.")
    app.declare_cmd("run", cmd_run)
    app.describe_cmd("run", "Run the application, optionally with tkintertester tests.")
    app.declare_cmd("unlock", cmd_unlock)
    app.describe_cmd("unlock", "Delete a stale Aspect Slicer lock file for this project.")
    app.main()


if __name__ == "__main__":
    main()

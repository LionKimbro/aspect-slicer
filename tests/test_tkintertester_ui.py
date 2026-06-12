import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

import tkintertester as harness
from tkintertester import harness as harness_module

from aspect_slicer import runtime_tests
from aspect_slicer import ui
from aspect_slicer.core import get_lock_path


def reset_harness_state():
    harness_module.tests.clear()
    harness_module.g["test_index"] = 0
    harness_module.g["current_test"] = None
    harness_module.g["test_done"] = False
    harness_module.g["exit_requested"] = False


def run_registered_tests(tmp_path):
    reset_harness_state()

    def app_entry():
        root = harness.get_root()
        win = tk.Toplevel(root)
        ui.start_in_root(win, tmp_path, "q", quit_fn=harness.quit)

    def app_reset():
        ui.reset_ui_state()

    harness.set_timeout(3000)
    harness.set_resetfn(app_reset)
    runtime_tests.register_tests()
    runtime_tests.register_shutdown_tests()
    harness.run_host(app_entry, "x")

    results = json.loads(harness.get_results("J"))
    assert all(row["status"] == "success" for row in results), harness.get_results()


def test_registered_gui_tests_with_tkintertester(tmp_path):
    run_registered_tests(tmp_path)
    assert not get_lock_path(tmp_path).exists()


def test_master_close_returns_from_normal_harness_runtime(tmp_path):
    code = f"""
import pathlib
import tkinter as tk
from tkintertester import harness
from aspect_slicer import ui

tmp_path = pathlib.Path({str(tmp_path)!r})

def app_entry():
    win = tk.Toplevel(harness.g["root"])
    ui.start_in_root(win, tmp_path, "q", quit_fn=harness.quit)
    win.after(20, ui.close_master_window)

harness.set_resetfn(ui.reset_ui_state)
harness.run_host(app_entry, "")
"""
    env = os.environ.copy()
    src_path = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = os.pathsep.join([str(src_path), env.get("PYTHONPATH", "")])
    result = subprocess.run([sys.executable, "-c", code], env=env, timeout=10)
    assert result.returncode == 0

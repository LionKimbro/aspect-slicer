import json
import tkinter as tk

import tkintertester as harness
from tkintertester import harness as harness_module

from aspect_slicer import runtime_tests
from aspect_slicer import ui


def test_master_create_and_lock_name_with_tkintertester(tmp_path):
    harness_module.tests.clear()
    harness_module.g["test_index"] = 0

    def app_entry():
        root = harness.get_root()
        win = tk.Toplevel(root)
        ui.start_in_root(win, tmp_path, "q", quit_fn=harness.quit)

    def app_reset():
        ui.reset_ui_state()

    harness.set_timeout(3000)
    harness.set_resetfn(app_reset)
    runtime_tests.register_tests()
    harness.run_host(app_entry, "x")

    results = json.loads(harness.get_results("J"))
    assert results[0]["status"] == "success", harness.get_results()

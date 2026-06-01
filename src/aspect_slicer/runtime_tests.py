import json

from tkintertester import harness

from . import ui


def register_tests():
    harness.set_resetfn(ui.reset_ui_state)
    harness.add_test(
        "Master window can create a design and lock its name",
        [
            step_master_window_exists,
            step_create_design,
            step_title_proposes_name,
            step_lock_name_enables_import_guarded_controls,
            step_audio_checkbox_persists_to_core_json,
        ],
    )


def step_master_window_exists():
    if "design-tree" not in ui.widgets:
        return "wait", 20
    tree = ui.widgets["design-tree"]
    if len(tree.get_children()) != 0:
        return "fail", "fresh project should start with no designs"
    return "next", None


def step_create_design():
    ui.handle_create_design()
    if len(ui.g["data"]["designs"]) != 1:
        return "fail", "create design did not add one design"
    if len(ui.design_windows) != 1:
        return "fail", "create design did not open a design window"
    state = next(iter(ui.design_windows.values()))
    browse_state = str(state["controls"]["browse"].cget("state"))
    if browse_state != "disabled":
        return "fail", "browse should be disabled before name lock"
    return "next", None


def step_title_proposes_name():
    state = next(iter(ui.design_windows.values()))
    state["vars"]["title"].set("Cool Print 7")
    ui.handle_title_changed(state)
    proposed = state["vars"]["name"].get()
    if proposed != "cool_print_7":
        return "fail", f"title proposed {proposed!r}, expected cool_print_7"
    return "next", None


def step_lock_name_enables_import_guarded_controls():
    state = next(iter(ui.design_windows.values()))
    ui.handle_lock_name(state)
    design = ui.get_window_design(state)
    if not design["name-locked"]:
        return "fail", "design name was not locked"
    if design["name"] != "cool_print_7":
        return "fail", f"locked name was {design['name']!r}"
    browse_state = str(state["controls"]["browse"].cget("state"))
    if browse_state != "normal":
        return "fail", "browse should be enabled after name lock"
    slice_state = str(state["controls"]["slice"].cget("state"))
    if slice_state != "disabled":
        return "fail", "slice should remain disabled until image import"
    return "next", None


def step_audio_checkbox_persists_to_core_json():
    ui.widgets["audio-var"].set(False)
    ui.handle_audio_changed()
    core_path = ui.g["execroot"] / ".aspect-slicer" / "core.json"
    with core_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data["config"]["audio"] is not False:
        return "fail", "audio checkbox did not persist false to core.json"
    return "success", None


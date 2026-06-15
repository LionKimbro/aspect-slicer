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
            step_search_filters_and_tree_sorts,
        ],
    )


def register_shutdown_tests():
    harness.set_resetfn(ui.reset_ui_state)
    harness.add_test(
        "Master window close requests harness shutdown",
        [
            step_master_window_is_ready,
            step_close_master_window,
        ],
        "q",
    )


def step_master_window_exists():
    result = step_master_window_is_ready()
    if result[0] != "next":
        return result
    tree = ui.widgets["design-tree"]
    if len(tree.get_children()) != 0:
        return "fail", "fresh project should start with no designs"
    return "next", None


def step_master_window_is_ready():
    if "design-tree" not in ui.widgets:
        return "wait", 20
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
    return "next", None


def step_search_filters_and_tree_sorts():
    first = next(iter(ui.g["data"]["designs"].values()))
    first["title"] = "Cool Print 7"
    first["tags"] = ["print"]
    series = ui.create_series(ui.g["data"], "Sumi")
    second = ui.create_design(ui.g["execroot"], ui.g["data"])
    second["name"] = "gengar_v2"
    second["name-locked"] = True
    second["title"] = "Gengar V2"
    second["tags"] = ["ghost"]
    second["series-uuid"] = series["uuid"]
    third = ui.create_design(ui.g["execroot"], ui.g["data"])
    third["name"] = "pikachu"
    third["name-locked"] = True
    third["title"] = "Electric Mouse"
    third["tags"] = ["yellow"]
    ui.refresh_design_tree()

    ui.widgets["design-search-var"].set("sumi")
    visible = ui.widgets["design-tree"].get_children()
    if visible != (second["uuid"],):
        return "fail", f"series search returned {visible!r}"

    ui.widgets["design-search-var"].set("ghost")
    visible = ui.widgets["design-tree"].get_children()
    if visible != (second["uuid"],):
        return "fail", f"tag search returned {visible!r}"

    ui.widgets["design-search-var"].set("")
    ui.set_design_tree_sort("title")
    visible = ui.widgets["design-tree"].get_children()
    expected = (first["uuid"], third["uuid"], second["uuid"])
    if visible != expected:
        return "fail", f"title sort returned {visible!r}, expected {expected!r}"
    return "success", None


def step_close_master_window():
    ui.close_master_window()
    if not harness.g["exit_requested"]:
        return "fail", "closing master window did not request harness exit"
    return "success", None

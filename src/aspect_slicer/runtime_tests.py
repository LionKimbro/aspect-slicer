import json

from PIL import Image
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
            step_design_debug_copy_and_button_labels,
            step_corner_zooms_and_arrow_nudge,
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


def step_design_debug_copy_and_button_labels():
    state = next(iter(ui.design_windows.values()))
    if state["controls"]["browse"].cget("text") != "Choose Image":
        return "fail", "browse button label was not updated"
    if state["controls"]["containing"].cget("text") != "Containing Folder":
        return "fail", "containing button label was not updated"
    if state["controls"]["open"].cget("text") != "See Image":
        return "fail", "open image button label was not updated"
    state["vars"]["note"].set("One-line debugging note")
    ui.commit_design_fields(state)
    if ui.get_window_design(state)["note"] != "One-line debugging note":
        return "fail", "note entry did not commit to the design"
    state["vars"]["tags"].set("print bad")
    ui.update_note_warning(state)
    if int(state["note-border"].cget("highlightthickness")) != 4:
        return "fail", "bad tag did not add the note warning border"
    if state["note-border"].cget("highlightbackground") != "#d12b2b":
        return "fail", "note warning border was not red"
    state["vars"]["tags"].set("print")
    ui.update_note_warning(state)
    if int(state["note-border"].cget("highlightthickness")) != 0:
        return "fail", "removing bad tag did not clear the note warning border"

    if "copy-design-source" in state["controls"]:
        return "fail", "copy design source should not be a visible button"
    for i in range(5):
        ui.handle_design_status_click(state)
    copied = state["window"].clipboard_get()
    design = ui.get_window_design(state)
    if f'"uuid": "{design["uuid"]}"' not in copied:
        return "fail", "five design status clicks did not copy the design JSON"
    if state["status"].cget("text") != "Copied design source to clipboard":
        return "fail", "copy design source did not update the status bar"
    if "master-menu" in ui.widgets:
        return "fail", "debug menu should not be visible on the master window"
    for i in range(5):
        ui.handle_master_status_click()
    debug_window = ui.g.get("debug-window")
    if not debug_window:
        return "fail", "five status clicks did not open the debug window"
    buttons = []
    for child in debug_window.winfo_children():
        buttons.extend(grandchild.cget("text") for grandchild in child.winfo_children() if hasattr(grandchild, "cget"))
    if "Open Project Folder" not in buttons or "View Source" not in buttons:
        return "fail", f"debug window buttons were {buttons!r}"
    return "next", None


def step_corner_zooms_and_arrow_nudge():
    state = next(iter(ui.design_windows.values()))
    design = ui.get_window_design(state)
    source = ui.g["execroot"] / "alpha-test.png"
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    for y in range(10, 90):
        for x in range(10, 90):
            image.putpixel((x, y), (12, 34, 56, 255))
    image.save(source)
    ui.import_image(ui.g["execroot"], design, source)
    design["crop-11x17"] = [10, 10, 90, 90]
    ui.load_design_into_window(state)
    ui.set_crop_mode(state, "11x17")

    if not state["zoom-frame"].grid_info():
        return "fail", "corner zoom frame was not shown in a single crop mode"
    if any(not canvas.find_all() for canvas in state["zoom-canvases"].values()):
        return "fail", "one or more corner zoom canvases were empty"
    if any(int(canvas.cget("width")) != 128 or int(canvas.cget("height")) != 128 for canvas in state["zoom-canvases"].values()):
        return "fail", "corner zoom canvases were not doubled to 128 by 128"
    if any(len(canvas.find_withtag("corner-reticle")) != 6 for canvas in state["zoom-canvases"].values()):
        return "fail", "one or more corner zoom canvases were missing the targeting reticle"
    if state["crop-has-transparent-corner"]:
        return "fail", "opaque crop corners were marked transparent"

    state["canvas"].focus_set()
    result = ui.handle_design_nudge(state, -1, 0)
    if result != "break":
        return "fail", "arrow nudge was not handled"
    if design["crop-11x17"] != [9, 10, 89, 90]:
        return "fail", f"arrow nudge produced {design['crop-11x17']!r}"
    if not state["crop-has-transparent-corner"]:
        return "fail", "transparent crop corners were not detected after nudge"
    if state["zoom-canvases"]["top-left"].cget("highlightbackground") != "#d12b2b":
        return "fail", "transparent corner zoom did not receive a red border"
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

    ui.widgets["design-search-var"].set("frame")
    design_uuids_before = set(ui.g["data"]["designs"])
    ui.handle_create_design()
    created_uuids = set(ui.g["data"]["designs"]) - design_uuids_before
    if ui.widgets["design-search-var"].get() != "frame":
        return "fail", "creating a design changed the active search filter"
    if len(created_uuids) != 1:
        return "fail", "creating a filtered design did not add exactly one design"
    created_uuid = created_uuids.pop()
    if ui.get_selected_design_uuid() is not None:
        return "fail", "filtered-out new design should not be selected"
    if created_uuid not in ui.design_windows:
        return "fail", "filtered-out new design window did not open"
    return "success", None


def step_close_master_window():
    ui.close_master_window()
    if not harness.g["exit_requested"]:
        return "fail", "closing master window did not request harness exit"
    return "success", None

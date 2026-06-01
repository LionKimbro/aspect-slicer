import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .constants import ASPECTS, DISPLAY_IMAGE_HEIGHT, SUPPORTED_EXTENSIONS
from .core import (
    create_design,
    create_series,
    design_display_name,
    design_has_slices,
    ensure_design_folders,
    ensure_project,
    find_series_by_name,
    get_crop_key,
    get_design_path,
    get_project_path,
    get_series_name,
    get_slices_path,
    lock_design_name,
    move_design_to_trash,
    normalize_identifier,
    normalize_tags,
    read_core,
    write_core,
)
from .imaging import (
    canvas_to_source,
    get_display_size,
    get_managed_image_path,
    import_image,
    make_drag_crop,
    slice_design,
    source_to_canvas,
)
from .sound import play_event_pattern


g = {
    "execroot": None,
    "root": None,
    "data": None,
    "dirty": False,
    "autosave-after-id": None,
    "sounds-enabled": True,
    "quit-fn": None,
}

widgets = {}
design_windows = {}


def run(execroot):
    root = tk.Tk()
    start_in_root(root, execroot)
    root.mainloop()


def start_in_root(root, execroot, flags="", quit_fn=None):
    reset_ui_state()
    g["execroot"] = Path(execroot)
    g["sounds-enabled"] = "q" not in flags
    g["quit-fn"] = quit_fn
    ensure_project(g["execroot"])
    g["data"] = read_core(g["execroot"])
    g["root"] = root
    root.title("Aspect Slicer")
    root.protocol("WM_DELETE_WINDOW", close_master_window)
    configure_style()
    build_master_window(root)
    refresh_design_tree()
    play("program-start")
    schedule_autosave()


def reset_ui_state():
    if g.get("autosave-after-id") and g.get("root"):
        try:
            g["root"].after_cancel(g["autosave-after-id"])
        except tk.TclError:
            pass
    for item in list(design_windows.values()):
        try:
            item["window"].destroy()
        except tk.TclError:
            pass
    if g.get("root"):
        for child in list(g["root"].winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass
    widgets.clear()
    design_windows.clear()
    g["execroot"] = None
    g["root"] = None
    g["data"] = None
    g["dirty"] = False
    g["autosave-after-id"] = None
    g["sounds-enabled"] = True
    g["quit-fn"] = None


def play(event_name):
    if not g.get("data"):
        return False
    return play_event_pattern(event_name, bool(g["sounds-enabled"] and g["data"]["config"]["audio"]))


def configure_style():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Treeview", rowheight=24)
    style.configure("Status.TLabel", padding=(8, 3))
    style.configure("Large.TEntry", padding=(4, 4))


def build_master_window(root):
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frame = ttk.Frame(root, padding=10)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    columns = ("name", "title", "series-name", "created-date")
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=16)
    for column, label, width in [
        ("name", "Name", 180),
        ("title", "Title", 260),
        ("series-name", "Series", 160),
        ("created-date", "Created", 100),
    ]:
        tree.heading(column, text=label)
        tree.column(column, width=width, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    tree.bind("<Double-1>", lambda event: open_selected_design())
    widgets["design-tree"] = tree

    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    controls = ttk.Frame(frame)
    controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    controls.columnconfigure(4, weight=1)
    ttk.Button(controls, text="Create New Design", command=handle_create_design).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(controls, text="Open", command=open_selected_design).grid(row=0, column=1, padx=(0, 6))
    ttk.Button(controls, text="Delete Design", command=handle_delete_design).grid(row=0, column=2, padx=(0, 18))

    audio_var = tk.BooleanVar(value=bool(g["data"]["config"]["audio"]))
    widgets["audio-var"] = audio_var
    ttk.Checkbutton(controls, text="audio", variable=audio_var, command=handle_audio_changed).grid(row=0, column=3, sticky="w")

    status = ttk.Label(frame, text="Saved", style="Status.TLabel", foreground="green")
    status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    widgets["master-status"] = status


def refresh_design_tree():
    tree = widgets["design-tree"]
    tree.delete(*tree.get_children())
    designs = sorted(g["data"]["designs"].values(), key=lambda d: (d["created-date"], d["title"], d["name"]))
    for design in designs:
        tree.insert(
            "",
            "end",
            iid=design["uuid"],
            values=(
                design_display_name(design),
                design["title"],
                get_series_name(g["data"], design["series-uuid"]),
                design["created-date"],
            ),
        )


def get_selected_design_uuid():
    selection = widgets["design-tree"].selection()
    if not selection:
        return None
    return selection[0]


def handle_create_design():
    design = create_design(g["execroot"], g["data"])
    mark_saved()
    refresh_design_tree()
    widgets["design-tree"].selection_set(design["uuid"])
    open_design_window(design["uuid"], focus_title=True)


def open_selected_design():
    design_uuid = get_selected_design_uuid()
    if not design_uuid:
        messagebox.showinfo("Aspect Slicer", "Select a design first.")
        return
    open_design_window(design_uuid)


def handle_delete_design():
    design_uuid = get_selected_design_uuid()
    if not design_uuid:
        messagebox.showinfo("Aspect Slicer", "Select a design first.")
        return
    design = g["data"]["designs"][design_uuid]
    if not messagebox.askyesno("Delete Design", f"Move {design_display_name(design)} to trash?"):
        return
    window = design_windows.get(design_uuid)
    if window:
        window["window"].destroy()
        del design_windows[design_uuid]
    move_design_to_trash(g["execroot"], g["data"], design_uuid)
    mark_saved()
    refresh_design_tree()
    play("delete-design")


def handle_audio_changed():
    g["data"]["config"]["audio"] = bool(widgets["audio-var"].get())
    save_now()


def open_design_window(design_uuid, focus_title=False):
    existing = design_windows.get(design_uuid)
    if existing:
        existing["window"].lift()
        if focus_title:
            existing["title-entry"].focus_set()
        return
    design = g["data"]["designs"][design_uuid]
    ensure_design_folders(g["execroot"], design)
    window = tk.Toplevel(g["root"])
    state = {
        "uuid": design_uuid,
        "window": window,
        "mode": "all",
        "photo": None,
        "image-item": None,
        "drag-anchor": None,
        "vars": {},
        "controls": {},
    }
    design_windows[design_uuid] = state
    window.title(make_design_window_title(design))
    window.protocol("WM_DELETE_WINDOW", lambda: close_design_window(design_uuid))
    build_design_window(state)
    load_design_into_window(state)
    redraw_canvas(state)
    play("open-design")
    if focus_title:
        state["title-entry"].focus_set()


def make_design_window_title(design):
    text = design["title"] or design["name"] or "unnamed"
    return f"Design: {text}"


def build_design_window(state):
    window = state["window"]
    window.columnconfigure(1, weight=1)
    window.rowconfigure(0, weight=1)
    left = ttk.Frame(window, padding=10)
    left.grid(row=0, column=0, sticky="nsw")
    right = ttk.Frame(window, padding=10)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)

    state["left-frame"] = left
    state["right-frame"] = right
    build_design_left_panel(state)
    build_design_canvas_panel(state)

    status = ttk.Label(window, text="Saved", style="Status.TLabel", foreground="green")
    status.grid(row=1, column=0, columnspan=2, sticky="ew")
    state["status"] = status


def build_design_left_panel(state):
    left = state["left-frame"]
    for i in range(2):
        left.columnconfigure(i, weight=1 if i == 1 else 0)

    ttk.Label(left, text="Design:").grid(row=0, column=0, sticky="w", pady=(0, 4))
    title_var = tk.StringVar()
    title_entry = ttk.Entry(left, textvariable=title_var, width=34, font=("Segoe UI", 14))
    title_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))
    title_entry.bind("<KeyRelease>", lambda event: handle_title_changed(state))
    title_entry.bind("<FocusOut>", lambda event: commit_design_fields(state))
    title_entry.bind("<Return>", lambda event: commit_design_fields(state))
    state["vars"]["title"] = title_var
    state["title-entry"] = title_entry

    ttk.Label(left, text="Name:").grid(row=1, column=0, sticky="w", pady=4)
    name_frame = ttk.Frame(left)
    name_frame.grid(row=1, column=1, sticky="ew", pady=4)
    name_frame.columnconfigure(0, weight=1)
    state["name-frame"] = name_frame

    ttk.Label(left, text="Created:").grid(row=2, column=0, sticky="w", pady=4)
    created = ttk.Label(left)
    created.grid(row=2, column=1, sticky="w", pady=4)
    state["created-label"] = created

    ttk.Label(left, text="Tags:").grid(row=3, column=0, sticky="w", pady=4)
    tags_var = tk.StringVar()
    tags_entry = ttk.Entry(left, textvariable=tags_var, width=34)
    tags_entry.grid(row=3, column=1, sticky="ew", pady=4)
    tags_entry.bind("<FocusOut>", lambda event: commit_design_fields(state))
    tags_entry.bind("<Return>", lambda event: commit_design_fields(state))
    state["vars"]["tags"] = tags_var

    ttk.Label(left, text="Series:").grid(row=4, column=0, sticky="w", pady=4)
    series_frame = ttk.Frame(left)
    series_frame.grid(row=4, column=1, sticky="ew", pady=4)
    series_frame.columnconfigure(0, weight=1)
    series_var = tk.StringVar()
    series_box = ttk.Combobox(series_frame, textvariable=series_var, width=24)
    series_box.grid(row=0, column=0, sticky="ew")
    series_box.bind("<FocusOut>", lambda event: commit_design_fields(state))
    series_box.bind("<KeyRelease>", lambda event: update_series_button_state(state))
    series_box.bind("<<ComboboxSelected>>", lambda event: commit_design_fields(state))
    create_series_btn = ttk.Button(series_frame, text="Create Series", command=lambda: handle_create_series(state))
    create_series_btn.grid(row=0, column=1, padx=(6, 0))
    state["vars"]["series"] = series_var
    state["series-box"] = series_box
    state["controls"]["create-series"] = create_series_btn

    ttk.Separator(left).grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)

    ttk.Label(left, text="Source:").grid(row=6, column=0, sticky="w", pady=4)
    source = ttk.Label(left, text="", wraplength=310)
    source.grid(row=6, column=1, sticky="ew", pady=4)
    state["source-label"] = source

    button_row = ttk.Frame(left)
    button_row.grid(row=7, column=1, sticky="ew", pady=4)
    browse = ttk.Button(button_row, text="Browse", command=lambda: handle_browse_image(state))
    browse.grid(row=0, column=0, padx=(0, 6))
    containing = ttk.Button(button_row, text="Containing", command=lambda: open_containing_folder(state))
    containing.grid(row=0, column=1, padx=(0, 6))
    open_button = ttk.Button(button_row, text="Open", command=lambda: open_source_image(state))
    open_button.grid(row=0, column=2)
    state["controls"]["browse"] = browse
    state["controls"]["containing"] = containing
    state["controls"]["open"] = open_button

    ttk.Label(left, text="Image Hash:").grid(row=8, column=0, sticky="w", pady=4)
    image_hash = ttk.Label(left, text="not loaded yet", wraplength=310)
    image_hash.grid(row=8, column=1, sticky="ew", pady=4)
    state["hash-label"] = image_hash

    ttk.Separator(left).grid(row=9, column=0, columnspan=2, sticky="ew", pady=8)

    slice_button = ttk.Button(left, text="Slice", command=lambda: handle_slice(state))
    slice_button.grid(row=10, column=0, sticky="ew", pady=4)
    view_button = ttk.Button(left, text="View Slices", command=lambda: open_slices_folder(state))
    view_button.grid(row=10, column=1, sticky="ew", padx=(6, 0), pady=4)
    state["controls"]["slice"] = slice_button
    state["controls"]["view-slices"] = view_button

    message = ttk.Label(left, text="", wraplength=360)
    message.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    state["message-label"] = message


def build_design_canvas_panel(state):
    right = state["right-frame"]
    canvas = tk.Canvas(right, width=450, height=DISPLAY_IMAGE_HEIGHT, background="#f5f5f5", highlightthickness=1, highlightbackground="#b9b9b9")
    canvas.grid(row=0, column=0, sticky="n")
    canvas.bind("<ButtonPress-1>", lambda event: handle_canvas_press(state, event))
    canvas.bind("<B1-Motion>", lambda event: handle_canvas_drag(state, event))
    canvas.bind("<ButtonRelease-1>", lambda event: handle_canvas_release(state, event))
    state["canvas"] = canvas

    mode_row = ttk.Frame(right)
    mode_row.grid(row=1, column=0, pady=(8, 0))
    buttons = []
    for label, mode in [("All", "all"), ("8.5 x 11", "8_5x11"), ("11 x 17", "11x17"), ("13 x 19", "13x19")]:
        btn = ttk.Button(mode_row, text=label, command=lambda m=mode: set_crop_mode(state, m))
        btn.grid(row=0, column=len(buttons), padx=3)
        buttons.append(btn)
    state["mode-buttons"] = buttons


def load_design_into_window(state):
    design = get_window_design(state)
    state["window"].title(make_design_window_title(design))
    state["vars"]["title"].set(design["title"])
    state["vars"]["tags"].set(" ".join(design["tags"]))
    state["vars"]["series"].set(get_series_name(g["data"], design["series-uuid"]))
    state["created-label"].configure(text=design["created-date"])
    state["source-label"].configure(text=design["source-file-path"] or "not loaded yet")
    state["hash-label"].configure(text=design["image-hash"] or "not loaded yet")
    state["series-box"].configure(values=sorted(series["name"] for series in g["data"]["series"].values()))
    build_name_widgets(state)
    update_design_controls(state)


def build_name_widgets(state):
    frame = state["name-frame"]
    for child in frame.winfo_children():
        child.destroy()
    design = get_window_design(state)
    if design["name-locked"]:
        ttk.Label(frame, text=design["name"]).grid(row=0, column=0, sticky="w")
    else:
        name_var = tk.StringVar(value=design["name"])
        entry = ttk.Entry(frame, textvariable=name_var, width=24)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<FocusOut>", lambda event: commit_name_field(state))
        entry.bind("<Return>", lambda event: commit_name_field(state))
        button = ttk.Button(frame, text="Lock Name", command=lambda: handle_lock_name(state))
        button.grid(row=0, column=1, padx=(6, 0))
        state["vars"]["name"] = name_var
        state["name-entry"] = entry


def update_design_controls(state):
    design = get_window_design(state)
    locked = design["name-locked"]
    has_image = bool(design["image-file"])
    has_crop = any(design[aspect["crop-key"]] for aspect in ASPECTS.values())
    has_source = bool(design["source-file-path"])
    state["controls"]["browse"].configure(state="normal" if locked else "disabled")
    state["controls"]["slice"].configure(state="normal" if locked and has_image and has_crop else "disabled")
    state["controls"]["containing"].configure(state="normal" if has_source else "disabled")
    state["controls"]["open"].configure(state="normal" if has_source else "disabled")
    state["controls"]["view-slices"].configure(state="normal" if design_has_slices(g["execroot"], design) else "disabled")
    if locked:
        state["message-label"].configure(text="")
    else:
        state["message-label"].configure(text="Choose and lock a design name before importing an image.")
    update_series_button_state(state)


def update_series_button_state(state):
    typed = normalize_identifier(state["vars"]["series"].get())
    exists = find_series_by_name(g["data"], typed) is not None
    state["controls"]["create-series"].configure(state="normal" if typed and not exists else "disabled")


def get_window_design(state):
    return g["data"]["designs"][state["uuid"]]


def commit_name_field(state):
    design = get_window_design(state)
    if design["name-locked"]:
        return
    design["name"] = normalize_identifier(state["vars"]["name"].get())
    state["vars"]["name"].set(design["name"])
    mark_dirty(state)


def handle_title_changed(state):
    design = get_window_design(state)
    if not design["name-locked"]:
        proposed = normalize_identifier(state["vars"]["title"].get())
        if "name" in state["vars"]:
            state["vars"]["name"].set(proposed)


def commit_design_fields(state):
    design = get_window_design(state)
    design["title"] = state["vars"]["title"].get()
    design["tags"] = normalize_tags(state["vars"]["tags"].get())
    state["vars"]["tags"].set(" ".join(design["tags"]))
    if not design["name-locked"] and "name" in state["vars"]:
        design["name"] = normalize_identifier(state["vars"]["name"].get())
        state["vars"]["name"].set(design["name"])
    series_text = state["vars"]["series"].get()
    normalized_series = normalize_identifier(series_text)
    series = find_series_by_name(g["data"], normalized_series)
    design["series-uuid"] = series["uuid"] if series else ""
    state["window"].title(make_design_window_title(design))
    refresh_design_tree()
    update_design_controls(state)
    mark_dirty(state)


def handle_create_series(state):
    typed = state["vars"]["series"].get()
    series = create_series(g["data"], typed)
    design = get_window_design(state)
    design["series-uuid"] = series["uuid"]
    state["vars"]["series"].set(series["name"])
    save_now()
    load_design_into_window(state)
    refresh_design_tree()


def handle_lock_name(state):
    commit_name_field(state)
    ok, message = lock_design_name(g["data"], state["uuid"], state["vars"]["name"].get())
    if not ok:
        messagebox.showerror("Lock Name", message)
        return
    save_now()
    load_design_into_window(state)
    refresh_design_tree()


def handle_browse_image(state):
    design = get_window_design(state)
    if not design["name-locked"]:
        messagebox.showinfo("Aspect Slicer", "Choose and lock a design name before importing an image.")
        return
    filetypes = [("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")]
    source = filedialog.askopenfilename(title="Select source image", filetypes=filetypes)
    if not source:
        return
    try:
        if Path(source).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("Choose a JPEG, PNG, or WEBP image.")
        import_image(g["execroot"], design, source)
    except Exception as exc:
        messagebox.showerror("Import Image", str(exc))
        return
    save_now()
    load_design_into_window(state)
    redraw_canvas(state)


def open_path(path):
    path = Path(path)
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_containing_folder(state):
    design = get_window_design(state)
    if design["source-file-path"]:
        open_path(Path(design["source-file-path"]).parent)


def open_source_image(state):
    design = get_window_design(state)
    if design["source-file-path"]:
        open_path(design["source-file-path"])


def open_slices_folder(state):
    design = get_window_design(state)
    open_path(get_slices_path(g["execroot"], design["uuid"]))


def handle_slice(state):
    commit_design_fields(state)
    design = get_window_design(state)
    try:
        written = slice_design(g["execroot"], design)
    except Exception as exc:
        messagebox.showerror("Slice", str(exc))
        return
    save_now()
    update_design_controls(state)
    state["message-label"].configure(text=f"Wrote {len(written)} slice file(s).")


def set_crop_mode(state, mode):
    state["mode"] = mode
    redraw_canvas(state)


def load_canvas_image(state):
    design = get_window_design(state)
    image_path = get_managed_image_path(g["execroot"], design)
    canvas = state["canvas"]
    if not image_path or not image_path.exists():
        state["photo"] = None
        canvas.configure(width=450, height=DISPLAY_IMAGE_HEIGHT)
        return False
    with Image.open(image_path) as image:
        display_size = get_display_size(*image.size)
        resized = image.resize(display_size)
    state["photo"] = ImageTk.PhotoImage(resized)
    canvas.configure(width=display_size[0], height=display_size[1])
    canvas.create_image(0, 0, image=state["photo"], anchor="nw", tags=("source-image",))
    return True


def redraw_canvas(state):
    canvas = state["canvas"]
    canvas.delete("all")
    design = get_window_design(state)
    if not load_canvas_image(state):
        canvas.create_text(225, DISPLAY_IMAGE_HEIGHT // 2, text="No image loaded", fill="#555")
        return
    modes = ASPECTS.keys() if state["mode"] == "all" else [state["mode"]]
    for mode in modes:
        aspect = ASPECTS[mode]
        crop = design[aspect["crop-key"]]
        if not crop:
            continue
        coords = source_to_canvas(crop, design["image-width"], design["image-height"])
        canvas.create_rectangle(*coords, outline=aspect["color"], width=3, tags=(aspect["crop-key"], "crop-rect"))


def handle_canvas_press(state, event):
    design = get_window_design(state)
    if state["mode"] == "all" or not design["name-locked"] or not design["image-file"]:
        return
    source_x, source_y = canvas_to_source(event.x, event.y, design["image-width"], design["image-height"])
    state["drag-anchor"] = (source_x, source_y)
    play("crop-start")


def handle_canvas_drag(state, event):
    update_drag_crop(state, event, save=False)


def handle_canvas_release(state, event):
    update_drag_crop(state, event, save=True)
    state["drag-anchor"] = None


def update_drag_crop(state, event, save):
    design = get_window_design(state)
    if not state["drag-anchor"] or state["mode"] == "all":
        return
    aspect = ASPECTS[state["mode"]]
    current_x, current_y = canvas_to_source(event.x, event.y, design["image-width"], design["image-height"])
    crop = make_drag_crop(
        state["drag-anchor"][0],
        state["drag-anchor"][1],
        current_x,
        current_y,
        aspect["ratio-width"],
        aspect["ratio-height"],
        design["image-width"],
        design["image-height"],
    )
    if not crop:
        return
    design[aspect["crop-key"]] = crop
    redraw_canvas(state)
    if save:
        save_now()
        play("crop-complete")


def mark_dirty(state=None):
    g["dirty"] = True
    update_status_labels(state)


def mark_saved():
    g["dirty"] = False
    update_status_labels()


def update_status_labels(state=None):
    text = "Unsaved" if g["dirty"] else "Saved"
    color = "red" if g["dirty"] else "green"
    if "master-status" in widgets:
        widgets["master-status"].configure(text=text, foreground=color)
    for item in design_windows.values():
        item["status"].configure(text=text, foreground=color)
    if state and "status" in state:
        state["status"].configure(text=text, foreground=color)


def save_now():
    write_core(g["execroot"], g["data"])
    mark_saved()


def schedule_autosave():
    if g["dirty"]:
        save_now()
    g["autosave-after-id"] = g["root"].after(5000, schedule_autosave)


def close_design_window(design_uuid):
    state = design_windows.get(design_uuid)
    if not state:
        return
    commit_design_fields(state)
    save_now()
    play("window-close")
    state["window"].destroy()
    del design_windows[design_uuid]


def close_master_window():
    for design_uuid in list(design_windows.keys()):
        state = design_windows.get(design_uuid)
        if state:
            commit_design_fields(state)
    save_now()
    play("program-close")
    root = g["root"]
    quit_fn = g.get("quit-fn")
    root.destroy()
    if quit_fn:
        quit_fn()

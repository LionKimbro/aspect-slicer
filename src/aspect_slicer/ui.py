import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .constants import ASPECTS, DISPLAY_IMAGE_HEIGHT, SUPPORTED_EXTENSIONS
from .core import (
    acquire_project_lock,
    create_design,
    create_series,
    design_display_name,
    design_has_slices,
    ensure_design_folders,
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
    release_project_lock,
    write_core,
)
from .imaging import (
    canvas_to_source,
    get_display_size,
    get_managed_image_path,
    import_image,
    make_drag_crop,
    move_crop,
    resize_crop,
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
    "lock": None,
    "sounds-enabled": True,
    "quit-fn": None,
}

widgets = {}
design_windows = {}

DESIGN_TREE_COLUMNS = [
    ("name", "Name", 180),
    ("title", "Title", 260),
    ("series-name", "Series", 160),
    ("created-date", "Created", 100),
]


def run(execroot):
    root = tk.Tk()
    start_in_root(root, execroot)
    root.mainloop()


def start_in_root(root, execroot, flags="", quit_fn=None):
    reset_ui_state()
    g["execroot"] = Path(execroot)
    g["sounds-enabled"] = "q" not in flags
    g["quit-fn"] = quit_fn
    ok, message, lock = acquire_project_lock(g["execroot"])
    if not ok:
        messagebox.showerror("Aspect Slicer", message)
        try:
            root.destroy()
        except tk.TclError:
            pass
        if quit_fn:
            quit_fn()
        reset_ui_state()
        return False
    g["lock"] = lock
    g["data"] = read_core(g["execroot"])
    g["root"] = root
    root.title("Aspect Slicer")
    root.protocol("WM_DELETE_WINDOW", close_master_window)
    configure_style()
    build_master_window(root)
    refresh_design_tree()
    play("program-start")
    schedule_autosave()
    return True


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
    release_ui_lock()
    widgets.clear()
    design_windows.clear()
    g["execroot"] = None
    g["root"] = None
    g["data"] = None
    g["dirty"] = False
    g["autosave-after-id"] = None
    g["lock"] = None
    g["sounds-enabled"] = True
    g["quit-fn"] = None


def release_ui_lock():
    if g.get("execroot") and g.get("lock"):
        release_project_lock(g["execroot"], g["lock"])
    g["lock"] = None


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
    frame.rowconfigure(1, weight=1)

    search_frame = ttk.Frame(frame)
    search_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    search_frame.columnconfigure(1, weight=1)
    ttk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky="w", padx=(0, 6))
    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=search_var)
    search_entry.grid(row=0, column=1, sticky="ew")
    search_var.trace_add("write", lambda *args: refresh_design_tree())
    widgets["design-search-var"] = search_var
    widgets["design-search-entry"] = search_entry
    widgets["design-sort-column"] = "created-date"
    widgets["design-sort-reverse"] = False

    columns = tuple(column for column, label, width in DESIGN_TREE_COLUMNS)
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=16)
    for column, label, width in DESIGN_TREE_COLUMNS:
        tree.heading(column, text=label, command=lambda c=column: set_design_tree_sort(c))
        tree.column(column, width=width, anchor="w")
    tree.grid(row=1, column=0, sticky="nsew")
    tree.bind("<Double-1>", lambda event: open_selected_design())
    widgets["design-tree"] = tree

    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    scrollbar.grid(row=1, column=1, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    controls = ttk.Frame(frame)
    controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    controls.columnconfigure(4, weight=1)
    ttk.Button(controls, text="Create New Design", command=handle_create_design).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(controls, text="Open", command=open_selected_design).grid(row=0, column=1, padx=(0, 6))
    ttk.Button(controls, text="Delete Design", command=handle_delete_design).grid(row=0, column=2, padx=(0, 18))

    audio_var = tk.BooleanVar(value=bool(g["data"]["config"]["audio"]))
    widgets["audio-var"] = audio_var
    ttk.Checkbutton(controls, text="audio", variable=audio_var, command=handle_audio_changed).grid(row=0, column=3, sticky="w")

    status = ttk.Label(frame, text="Saved", style="Status.TLabel", foreground="green")
    status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    widgets["master-status"] = status


def refresh_design_tree():
    tree = widgets["design-tree"]
    selection = tree.selection()
    tree.delete(*tree.get_children())
    update_design_tree_headings()
    designs = get_visible_designs()
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
    if selection and selection[0] in tree.get_children():
        tree.selection_set(selection[0])


def get_visible_designs():
    designs = [design for design in g["data"]["designs"].values() if design_matches_search(design)]
    sort_column = widgets.get("design-sort-column", "created-date")
    sort_reverse = bool(widgets.get("design-sort-reverse", False))
    return sorted(designs, key=lambda design: design_sort_key(design, sort_column), reverse=sort_reverse)


def get_design_search_text():
    search_var = widgets.get("design-search-var")
    if not search_var:
        return ""
    return search_var.get().strip()


def design_matches_search(design):
    text = get_design_search_text()
    if not text:
        return True
    text_lower = text.lower()
    series = find_series_by_name(g["data"], text)
    if series:
        return design["series-uuid"] == series["uuid"]
    fields = [
        design_display_name(design),
        design["title"],
        get_series_name(g["data"], design["series-uuid"]),
    ]
    fields.extend(design["tags"])
    return any(text_lower in field.lower() for field in fields)


def design_sort_key(design, column):
    series_name = get_series_name(g["data"], design["series-uuid"])
    values = {
        "name": design_display_name(design),
        "title": design["title"],
        "series-name": series_name,
        "created-date": design["created-date"],
    }
    return (str(values.get(column, "")).lower(), design["created-date"], design["title"].lower(), design_display_name(design).lower())


def set_design_tree_sort(column):
    current = widgets.get("design-sort-column", "created-date")
    if column == current:
        widgets["design-sort-reverse"] = not bool(widgets.get("design-sort-reverse", False))
    else:
        widgets["design-sort-column"] = column
        widgets["design-sort-reverse"] = False
    refresh_design_tree()


def update_design_tree_headings():
    tree = widgets["design-tree"]
    sort_column = widgets.get("design-sort-column", "created-date")
    sort_reverse = bool(widgets.get("design-sort-reverse", False))
    marker = " v" if sort_reverse else " ^"
    for column, label, width in DESIGN_TREE_COLUMNS:
        tree.heading(column, text=label + marker if column == sort_column else label, command=lambda c=column: set_design_tree_sort(c))


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
        "drag-action": None,
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

    instruction = ttk.Label(right, text="", foreground="#555")
    instruction.grid(row=2, column=0, pady=(8, 0), sticky="w")
    state["canvas-instruction"] = instruction


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
    update_canvas_instruction(state)


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
    update_canvas_instruction(state)
    redraw_canvas(state)


def update_canvas_instruction(state):
    if state["mode"] == "all":
        state["canvas-instruction"].configure(text="")
    else:
        state["canvas-instruction"].configure(text="Hold down shift while clicking, to create a new region.")


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
        if state["mode"] != "all":
            draw_crop_handles(canvas, coords, aspect["color"])


def draw_crop_handles(canvas, coords, color):
    x0, y0, x1, y1 = coords
    points = {
        "nw": (x0, y0),
        "n": ((x0 + x1) / 2, y0),
        "ne": (x1, y0),
        "e": (x1, (y0 + y1) / 2),
        "se": (x1, y1),
        "s": ((x0 + x1) / 2, y1),
        "sw": (x0, y1),
        "w": (x0, (y0 + y1) / 2),
    }
    radius = 5
    for handle, (x, y) in points.items():
        canvas.create_rectangle(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill="white",
            outline=color,
            width=2,
            tags=("crop-handle", f"handle-{handle}"),
        )


def handle_canvas_press(state, event):
    design = get_window_design(state)
    if state["mode"] == "all" or not design["name-locked"] or not design["image-file"]:
        return
    source_x, source_y = canvas_to_source(event.x, event.y, design["image-width"], design["image-height"])
    crop_key = get_crop_key(state["mode"])
    crop = design[crop_key]
    shift_is_down = bool(event.state & 0x0001)
    if crop and not shift_is_down:
        handle = hit_test_crop_handle(state, event.x, event.y, crop)
        if handle:
            state["drag-action"] = {"kind": "resize", "handle": handle, "original-crop": list(crop)}
            play("crop-start")
            return
        if source_point_in_crop(source_x, source_y, crop):
            state["drag-action"] = {"kind": "move", "start": (source_x, source_y), "original-crop": list(crop)}
            play("crop-start")
            return
    if crop and shift_is_down and source_point_in_crop(source_x, source_y, crop):
        design[crop_key] = None
        redraw_canvas(state)
    state["drag-action"] = {"kind": "new", "anchor": (source_x, source_y)}
    play("crop-start")


def handle_canvas_drag(state, event):
    update_drag_crop(state, event, save=False)


def handle_canvas_release(state, event):
    update_drag_crop(state, event, save=True)
    state["drag-anchor"] = None
    state["drag-action"] = None


def update_drag_crop(state, event, save):
    design = get_window_design(state)
    if not state["drag-action"] or state["mode"] == "all":
        return
    aspect = ASPECTS[state["mode"]]
    current_x, current_y = canvas_to_source(event.x, event.y, design["image-width"], design["image-height"])
    action = state["drag-action"]
    if action["kind"] == "new":
        crop = make_drag_crop(
            action["anchor"][0],
            action["anchor"][1],
            current_x,
            current_y,
            aspect["ratio-width"],
            aspect["ratio-height"],
            design["image-width"],
            design["image-height"],
        )
    elif action["kind"] == "move":
        delta_x = current_x - action["start"][0]
        delta_y = current_y - action["start"][1]
        crop = move_crop(action["original-crop"], delta_x, delta_y, design["image-width"], design["image-height"])
    else:
        crop = resize_crop(
            action["original-crop"],
            action["handle"],
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


def source_point_in_crop(source_x, source_y, crop):
    x0, y0, x1, y1 = crop
    return x0 <= source_x <= x1 and y0 <= source_y <= y1


def hit_test_crop_handle(state, canvas_x, canvas_y, crop):
    design = get_window_design(state)
    x0, y0, x1, y1 = source_to_canvas(crop, design["image-width"], design["image-height"])
    points = {
        "nw": (x0, y0),
        "n": ((x0 + x1) / 2, y0),
        "ne": (x1, y0),
        "e": (x1, (y0 + y1) / 2),
        "se": (x1, y1),
        "s": ((x0 + x1) / 2, y1),
        "sw": (x0, y1),
        "w": (x0, (y0 + y1) / 2),
    }
    for handle, (x, y) in points.items():
        if abs(canvas_x - x) <= 7 and abs(canvas_y - y) <= 7:
            return handle
    return None


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
    if not g.get("root"):
        return
    for design_uuid in list(design_windows.keys()):
        state = design_windows.get(design_uuid)
        if state:
            commit_design_fields(state)
            try:
                state["window"].destroy()
            except tk.TclError:
                pass
            design_windows.pop(design_uuid, None)
    if g.get("autosave-after-id"):
        try:
            g["root"].after_cancel(g["autosave-after-id"])
        except tk.TclError:
            pass
        g["autosave-after-id"] = None
    save_now()
    play("program-close")
    root = g["root"]
    quit_fn = g.get("quit-fn")
    try:
        root.destroy()
    except tk.TclError:
        pass
    release_ui_lock()
    g["root"] = None
    if quit_fn:
        quit_fn()

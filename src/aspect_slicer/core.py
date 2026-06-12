import datetime as _datetime
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .constants import ASPECTS, CORE_JSON, LOCK_JSON, PROJECT_DIR, SUPPORTED_EXTENSIONS


IDENTIFIER_RE = re.compile(r"^[a-z0-9_]+$")


def today_string():
    return _datetime.date.today().isoformat()


def normalize_identifier(text):
    value = text.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def normalize_tags(text):
    tags = []
    seen = set()
    for token in text.split():
        normalized = normalize_identifier(token)
        if normalized and normalized not in seen:
            seen.add(normalized)
            tags.append(normalized)
    return tags


def make_core():
    return {
        "config": {"audio": True},
        "designs": {},
        "series": {},
    }


def normalize_core(data):
    if not isinstance(data, dict):
        return make_core()
    data.setdefault("config", {})
    data["config"].setdefault("audio", True)
    data.setdefault("designs", {})
    data.setdefault("series", {})
    for design_uuid, design in list(data["designs"].items()):
        data["designs"][design_uuid] = normalize_design(design)
    for series_uuid, series in list(data["series"].items()):
        data["series"][series_uuid] = normalize_series(series)
    return data


def normalize_design(design):
    defaults = make_design()
    defaults.update(design)
    design.clear()
    design.update(defaults)
    return design


def normalize_series(series):
    defaults = make_series(series.get("name", ""))
    defaults.update(series)
    series.clear()
    series.update(defaults)
    return series


def get_project_path(execroot):
    return Path(execroot) / PROJECT_DIR


def get_core_path(execroot):
    return get_project_path(execroot) / CORE_JSON


def get_lock_path(execroot):
    return get_project_path(execroot) / LOCK_JSON


def get_design_path(execroot, design_uuid):
    return get_project_path(execroot) / "designs" / design_uuid


def get_slices_path(execroot, design_uuid):
    return get_design_path(execroot, design_uuid) / "slices"


def ensure_project(execroot):
    project = get_project_path(execroot)
    (project / "designs").mkdir(parents=True, exist_ok=True)
    (project / "trash").mkdir(parents=True, exist_ok=True)
    core_path = project / CORE_JSON
    if not core_path.exists():
        write_core(execroot, make_core())
    return project


def read_core(execroot):
    ensure_project(execroot)
    with get_core_path(execroot).open("r", encoding="utf-8") as f:
        data = normalize_core(json.load(f))
    if recover_orphan_designs(execroot, data):
        write_core(execroot, data)
    return data


def write_core(execroot, data):
    project = get_project_path(execroot)
    project.mkdir(parents=True, exist_ok=True)
    normalize_core(data)
    recover_orphan_designs(execroot, data)
    write_design_snapshots(execroot, data)
    tmp_path = project / f"{CORE_JSON}.tmp"
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, project / CORE_JSON)


def make_project_lock():
    return {
        "uuid": str(uuid.uuid4()),
        "pid": os.getpid(),
        "created-date": _datetime.datetime.now().isoformat(timespec="seconds"),
    }


def read_project_lock(execroot):
    lock_path = get_lock_path(execroot)
    try:
        with lock_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def describe_project_lock(execroot):
    lock = read_project_lock(execroot)
    if not lock:
        return f"Aspect Slicer is already running. Lock file: {get_lock_path(execroot)}"
    return (
        "Aspect Slicer is already running "
        f"(pid {lock.get('pid', 'unknown')}, lock {lock.get('uuid', 'unknown')}). "
        f"Lock file: {get_lock_path(execroot)}"
    )


def acquire_project_lock(execroot):
    ensure_project(execroot)
    lock_path = get_lock_path(execroot)
    lock = make_project_lock()
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False, describe_project_lock(execroot), None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2)
        f.write("\n")
    return True, "", lock


def release_project_lock(execroot, lock=None, force=False):
    lock_path = get_lock_path(execroot)
    if not lock_path.exists():
        return False
    if not force:
        if not lock:
            return False
        existing = read_project_lock(execroot)
        if existing.get("uuid") != lock.get("uuid"):
            return False
    lock_path.unlink()
    return True


def make_design():
    return {
        "uuid": str(uuid.uuid4()),
        "name": "",
        "name-locked": False,
        "title": "",
        "tags": [],
        "series-uuid": "",
        "created-date": today_string(),
        "source-file-path": "",
        "image-file": "",
        "image-hash": "",
        "image-width": None,
        "image-height": None,
        "crop-8-5x11": None,
        "crop-11x17": None,
        "crop-13x19": None,
    }


def make_recovered_design(design_uuid, design_path):
    design = make_design()
    design["uuid"] = design_uuid
    design["created-date"] = _datetime.date.fromtimestamp(design_path.stat().st_mtime).isoformat()
    recover_image_fields(design, design_path)
    recover_name_from_slices(design, design_path)
    return design


def make_series(name, title=""):
    normalized = normalize_identifier(name)
    return {
        "uuid": str(uuid.uuid4()),
        "name": normalized,
        "title": title or name.strip() or normalized,
        "tags": [],
        "created-date": today_string(),
    }


def ensure_design_folders(execroot, design):
    design_path = get_design_path(execroot, design["uuid"])
    (design_path / "slices").mkdir(parents=True, exist_ok=True)
    return design_path


def get_design_snapshot_path(execroot, design_uuid):
    return get_design_path(execroot, design_uuid) / "design.json"


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_design_snapshot(execroot, design):
    ensure_design_folders(execroot, design)
    write_json_atomic(get_design_snapshot_path(execroot, design["uuid"]), design)


def write_design_snapshots(execroot, data):
    for design in data.get("designs", {}).values():
        write_design_snapshot(execroot, design)


def read_design_snapshot(path):
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return normalize_design(data)


def recover_orphan_designs(execroot, data):
    designs_path = get_project_path(execroot) / "designs"
    if not designs_path.exists():
        return False
    recovered = False
    for design_path in designs_path.iterdir():
        if not design_path.is_dir() or design_path.name in data["designs"]:
            continue
        snapshot = read_design_snapshot(design_path / "design.json")
        design = snapshot if snapshot else make_recovered_design(design_path.name, design_path)
        design["uuid"] = design_path.name
        data["designs"][design["uuid"]] = design
        recovered = True
    return recovered


def recover_image_fields(design, design_path):
    from PIL import Image

    for image_file in sorted(set(SUPPORTED_EXTENSIONS.values())):
        image_path = design_path / image_file
        if not image_path.exists():
            continue
        with Image.open(image_path) as image:
            width, height = image.size
        design["image-file"] = image_file
        design["image-width"] = width
        design["image-height"] = height
        design["image-hash"] = file_sha256(image_path)
        return


def recover_name_from_slices(design, design_path):
    slices_path = design_path / "slices"
    if not slices_path.exists():
        return
    suffixes = [f"_{aspect['filename-token']}.png" for aspect in ASPECTS.values()]
    for path in sorted(slices_path.iterdir()):
        if not path.is_file():
            continue
        for suffix in suffixes:
            if path.name.endswith(suffix):
                design["name"] = path.name[: -len(suffix)]
                design["title"] = design["name"].replace("_", " ")
                design["name-locked"] = bool(design["name"])
                return


def create_design(execroot, data):
    design = make_design()
    data["designs"][design["uuid"]] = design
    ensure_design_folders(execroot, design)
    write_core(execroot, data)
    return design


def create_series(data, typed_name):
    series = make_series(typed_name)
    data["series"][series["uuid"]] = series
    return series


def get_series_name(data, series_uuid):
    if not series_uuid:
        return ""
    series = data["series"].get(series_uuid)
    if not series:
        return ""
    return series["name"]


def find_series_by_name(data, name):
    normalized = normalize_identifier(name)
    for series in data["series"].values():
        if series["name"] == normalized:
            return series
    return None


def design_display_name(design):
    if design["name"]:
        return design["name"]
    return f"<unnamed {design['uuid'][:4]}>"


def validate_design_name(data, design_uuid, name):
    normalized = normalize_identifier(name)
    if not normalized:
        return False, "Name cannot be blank.", normalized
    if not IDENTIFIER_RE.match(normalized):
        return False, "Name must use lowercase letters, digits, and underscores.", normalized
    for other_uuid, design in data["designs"].items():
        if other_uuid != design_uuid and design["name"] == normalized:
            return False, "Name must be unique.", normalized
    return True, "", normalized


def lock_design_name(data, design_uuid, name):
    design = data["designs"][design_uuid]
    ok, message, normalized = validate_design_name(data, design_uuid, name)
    if not ok:
        return False, message
    design["name"] = normalized
    design["name-locked"] = True
    return True, ""


def move_design_to_trash(execroot, data, design_uuid):
    design = data["designs"][design_uuid]
    source = get_design_path(execroot, design_uuid)
    trash_root = get_project_path(execroot) / "trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    target = trash_root / design_uuid
    counter = 2
    while target.exists():
        target = trash_root / f"{design_uuid}-{counter}"
        counter += 1
    if source.exists():
        source.mkdir(parents=True, exist_ok=True)
        with (source / "design.json").open("w", encoding="utf-8") as f:
            json.dump(design, f, indent=2)
            f.write("\n")
        shutil.move(str(source), str(target))
    else:
        target.mkdir(parents=True, exist_ok=True)
        with (target / "design.json").open("w", encoding="utf-8") as f:
            json.dump(design, f, indent=2)
            f.write("\n")
    del data["designs"][design_uuid]
    write_core(execroot, data)
    return target


def design_has_slices(execroot, design):
    slices = get_slices_path(execroot, design["uuid"])
    return slices.exists() and any(path.is_file() for path in slices.iterdir())


def get_crop_key(mode):
    return ASPECTS[mode]["crop-key"]


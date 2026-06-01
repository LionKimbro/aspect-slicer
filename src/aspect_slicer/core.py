import datetime as _datetime
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .constants import ASPECTS, CORE_JSON, PROJECT_DIR


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
    return data


def get_project_path(execroot):
    return Path(execroot) / PROJECT_DIR


def get_core_path(execroot):
    return get_project_path(execroot) / CORE_JSON


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
        return normalize_core(json.load(f))


def write_core(execroot, data):
    project = get_project_path(execroot)
    project.mkdir(parents=True, exist_ok=True)
    tmp_path = project / f"{CORE_JSON}.tmp"
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, project / CORE_JSON)


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


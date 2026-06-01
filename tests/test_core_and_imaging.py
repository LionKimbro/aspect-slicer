import json

from PIL import Image

from aspect_slicer.core import (
    create_design,
    design_has_slices,
    ensure_project,
    lock_design_name,
    move_design_to_trash,
    normalize_identifier,
    normalize_tags,
    read_core,
)
from aspect_slicer.imaging import default_centered_crop, import_image, make_drag_crop, move_crop, resize_crop, slice_design


def test_normalize_identifier_and_tags():
    assert normalize_identifier("Cool-Print #7!!") == "cool_print_7"
    assert normalize_identifier("   Dragon Poster ") == "dragon_poster"
    assert normalize_identifier("Robert's Best One") == "robert_s_best_one"
    assert normalize_tags("Cool cool PRINT #7!!") == ["cool", "print", "7"]


def test_default_centered_crop_uses_integer_ratio_multiple():
    assert default_centered_crop(1696, 2528, 17, 22) == [6, 175, 1689, 2353]
    assert default_centered_crop(1696, 2528, 11, 17) == [34, 6, 1662, 2522]
    assert default_centered_crop(1696, 2528, 13, 19) == [3, 29, 1693, 2499]


def test_drag_crop_contains_current_point_and_clamps_to_bounds():
    assert make_drag_crop(10, 20, 34, 59, 11, 17, 100, 100) == [10, 20, 43, 71]
    assert make_drag_crop(90, 90, 120, 120, 11, 17, 100, 100) is None
    assert make_drag_crop(70, 50, 99, 99, 13, 19, 100, 100) == [70, 50, 96, 88]


def test_drag_crop_does_not_aspect_quantize_top_left_anchor():
    crop = make_drag_crop(23, 37, 90, 140, 17, 22, 200, 200)
    assert crop[:2] == [23, 37]
    assert (crop[2] - crop[0]) % 17 == 0
    assert (crop[3] - crop[1]) % 22 == 0


def test_move_crop_preserves_size_and_clamps_to_image():
    assert move_crop([20, 30, 70, 90], 15, -10, 100, 100) == [35, 20, 85, 80]
    assert move_crop([20, 30, 70, 90], 100, 100, 100, 100) == [50, 40, 100, 100]
    assert move_crop([20, 30, 70, 90], -100, -100, 100, 100) == [0, 0, 50, 60]


def test_resize_crop_corner_and_edge_preserve_ratio_and_bounds():
    corner = resize_crop([20, 20, 64, 88], "se", 90, 140, 11, 17, 100, 150)
    assert corner == [20, 20, 97, 139]
    edge = resize_crop([20, 20, 64, 88], "e", 95, 80, 11, 17, 100, 150)
    assert edge[0] == 20
    assert edge[2] <= 100
    assert (edge[2] - edge[0]) % 11 == 0
    assert (edge[3] - edge[1]) % 17 == 0


def test_project_create_import_slice_and_trash(tmp_path):
    ensure_project(tmp_path)
    data = read_core(tmp_path)
    design = create_design(tmp_path, data)
    ok, message = lock_design_name(data, design["uuid"], "Cool Print 7")
    assert ok, message

    source = tmp_path / "source.png"
    Image.new("RGB", (110, 170), (12, 34, 56)).save(source)
    imported = import_image(tmp_path, design, source)

    assert imported.name == "image.png"
    assert design["source-file-path"] == str(source)
    assert design["image-width"] == 110
    assert design["image-height"] == 170
    assert len(design["image-hash"]) == 64
    assert design["crop-11x17"] == [0, 0, 110, 170]

    design["crop-8-5x11"] = None
    design["crop-13x19"] = None
    written = slice_design(tmp_path, design)
    assert len(written) == 1
    assert written[0].name == "cool_print_7_11x17.png"
    assert design_has_slices(tmp_path, design)

    data["designs"][design["uuid"]] = design
    trash_path = move_design_to_trash(tmp_path, data, design["uuid"])
    assert trash_path.exists()
    assert not (tmp_path / ".aspect-slicer" / "designs" / design["uuid"]).exists()
    with (trash_path / "design.json").open("r", encoding="utf-8") as f:
        snapshot = json.load(f)
    assert snapshot["name"] == "cool_print_7"
    assert design["uuid"] not in data["designs"]

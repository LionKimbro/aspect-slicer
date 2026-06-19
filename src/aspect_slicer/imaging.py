import hashlib
import math
import shutil
from pathlib import Path

from PIL import Image

from .constants import ASPECTS, DISPLAY_IMAGE_HEIGHT, SUPPORTED_EXTENSIONS
from .core import ensure_design_folders, get_design_path, get_slices_path


NEAR_STANDARD_SOURCE_SIZE = {
    "width-min": 1694,
    "width-max": 1698,
    "height-min": 2526,
    "height-max": 2530,
}

NEAR_STANDARD_SOURCE_CROPS = {
    "crop-8-5x11": [6, 175, 1689, 2353],
    "crop-11x17": [48, 6, 1654, 2488],
    "crop-13x19": [13, 43, 1677, 2475],
}


def get_managed_image_path(execroot, design):
    if not design["image-file"]:
        return None
    return get_design_path(execroot, design["uuid"]) / design["image-file"]


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def default_centered_crop(image_width, image_height, ratio_width, ratio_height):
    n = min(image_width // ratio_width, image_height // ratio_height)
    if n < 1:
        return None
    crop_width = ratio_width * n
    crop_height = ratio_height * n
    x0 = (image_width - crop_width) // 2
    y0 = (image_height - crop_height) // 2
    return [x0, y0, x0 + crop_width, y0 + crop_height]


def image_is_near_standard_source_size(image_width, image_height):
    return (
        NEAR_STANDARD_SOURCE_SIZE["width-min"] <= image_width <= NEAR_STANDARD_SOURCE_SIZE["width-max"]
        and NEAR_STANDARD_SOURCE_SIZE["height-min"] <= image_height <= NEAR_STANDARD_SOURCE_SIZE["height-max"]
    )


def default_import_crop(image_width, image_height, aspect):
    crop_key = aspect["crop-key"]
    if image_is_near_standard_source_size(image_width, image_height):
        return list(NEAR_STANDARD_SOURCE_CROPS[crop_key])
    return default_centered_crop(
        image_width,
        image_height,
        aspect["ratio-width"],
        aspect["ratio-height"],
    )


def make_drag_crop(anchor_x, anchor_y, current_x, current_y, ratio_width, ratio_height, image_width, image_height):
    """Create an aspect-correct drag rectangle.

    The anchor is the user's chosen top-left source pixel. It is clamped to
    image bounds but not snapped to the aspect-ratio grid; only width and
    height are quantized to integer multiples of the requested ratio.
    """
    anchor_x = max(0, min(int(anchor_x), image_width - 1))
    anchor_y = max(0, min(int(anchor_y), image_height - 1))
    current_x = max(anchor_x + 1, min(int(current_x), image_width))
    current_y = max(anchor_y + 1, min(int(current_y), image_height))
    required_width = current_x - anchor_x
    required_height = current_y - anchor_y
    n = max(
        math.ceil(required_width / ratio_width),
        math.ceil(required_height / ratio_height),
        1,
    )
    max_n = min((image_width - anchor_x) // ratio_width, (image_height - anchor_y) // ratio_height)
    if max_n < 1:
        return None
    n = min(n, max_n)
    return [anchor_x, anchor_y, anchor_x + ratio_width * n, anchor_y + ratio_height * n]


def move_crop(crop, delta_x, delta_y, image_width, image_height):
    x0, y0, x1, y1 = crop
    width = x1 - x0
    height = y1 - y0
    new_x0 = max(0, min(x0 + int(delta_x), image_width - width))
    new_y0 = max(0, min(y0 + int(delta_y), image_height - height))
    return [new_x0, new_y0, new_x0 + width, new_y0 + height]


def get_crop_corner_pixels(crop):
    x0, y0, x1, y1 = crop
    return {
        "top-left": (x0, y0),
        "top-right": (x1 - 1, y0),
        "bottom-left": (x0, y1 - 1),
        "bottom-right": (x1 - 1, y1 - 1),
    }


def get_transparent_crop_corners(image, crop):
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return {
        name: rgba.getpixel(point)[3] < 255
        for name, point in get_crop_corner_pixels(crop).items()
    }


def resize_crop(crop, handle, current_x, current_y, ratio_width, ratio_height, image_width, image_height):
    current_x = max(0, min(int(current_x), image_width))
    current_y = max(0, min(int(current_y), image_height))
    if handle in {"nw", "ne", "sw", "se"}:
        return resize_crop_corner(crop, handle, current_x, current_y, ratio_width, ratio_height, image_width, image_height)
    return resize_crop_edge(crop, handle, current_x, current_y, ratio_width, ratio_height, image_width, image_height)


def resize_crop_corner(crop, handle, current_x, current_y, ratio_width, ratio_height, image_width, image_height):
    x0, y0, x1, y1 = crop
    if handle == "nw":
        fixed_x, fixed_y = x1, y1
        required_width = max(1, fixed_x - current_x)
        required_height = max(1, fixed_y - current_y)
        max_n = min(fixed_x // ratio_width, fixed_y // ratio_height)
        n = choose_resize_n(required_width, required_height, ratio_width, ratio_height, max_n)
        return None if n is None else [fixed_x - ratio_width * n, fixed_y - ratio_height * n, fixed_x, fixed_y]
    if handle == "ne":
        fixed_x, fixed_y = x0, y1
        required_width = max(1, current_x - fixed_x)
        required_height = max(1, fixed_y - current_y)
        max_n = min((image_width - fixed_x) // ratio_width, fixed_y // ratio_height)
        n = choose_resize_n(required_width, required_height, ratio_width, ratio_height, max_n)
        return None if n is None else [fixed_x, fixed_y - ratio_height * n, fixed_x + ratio_width * n, fixed_y]
    if handle == "sw":
        fixed_x, fixed_y = x1, y0
        required_width = max(1, fixed_x - current_x)
        required_height = max(1, current_y - fixed_y)
        max_n = min(fixed_x // ratio_width, (image_height - fixed_y) // ratio_height)
        n = choose_resize_n(required_width, required_height, ratio_width, ratio_height, max_n)
        return None if n is None else [fixed_x - ratio_width * n, fixed_y, fixed_x, fixed_y + ratio_height * n]
    fixed_x, fixed_y = x0, y0
    required_width = max(1, current_x - fixed_x)
    required_height = max(1, current_y - fixed_y)
    max_n = min((image_width - fixed_x) // ratio_width, (image_height - fixed_y) // ratio_height)
    n = choose_resize_n(required_width, required_height, ratio_width, ratio_height, max_n)
    return None if n is None else [fixed_x, fixed_y, fixed_x + ratio_width * n, fixed_y + ratio_height * n]


def resize_crop_edge(crop, handle, current_x, current_y, ratio_width, ratio_height, image_width, image_height):
    x0, y0, x1, y1 = crop
    center_x = (x0 + x1) // 2
    center_y = (y0 + y1) // 2
    if handle in {"w", "e"}:
        fixed_x = x1 if handle == "w" else x0
        required_width = max(1, abs(current_x - fixed_x))
        n = max(1, math.ceil(required_width / ratio_width))
        max_n = min(image_width // ratio_width, image_height // ratio_height)
        n = min(n, max_n)
        width = ratio_width * n
        height = ratio_height * n
        if handle == "w":
            x0 = max(0, x1 - width)
            x1 = x0 + width
        else:
            x1 = min(image_width, x0 + width)
            x0 = x1 - width
        y0 = max(0, min(center_y - height // 2, image_height - height))
        return [x0, y0, x1, y0 + height]
    fixed_y = y1 if handle == "n" else y0
    required_height = max(1, abs(current_y - fixed_y))
    n = max(1, math.ceil(required_height / ratio_height))
    max_n = min(image_width // ratio_width, image_height // ratio_height)
    n = min(n, max_n)
    width = ratio_width * n
    height = ratio_height * n
    if handle == "n":
        y0 = max(0, y1 - height)
        y1 = y0 + height
    else:
        y1 = min(image_height, y0 + height)
        y0 = y1 - height
    x0 = max(0, min(center_x - width // 2, image_width - width))
    return [x0, y0, x0 + width, y1]


def choose_resize_n(required_width, required_height, ratio_width, ratio_height, max_n):
    if max_n < 1:
        return None
    n = max(
        math.ceil(required_width / ratio_width),
        math.ceil(required_height / ratio_height),
        1,
    )
    return min(n, max_n)


def get_display_size(image_width, image_height):
    if not image_width or not image_height:
        return 1, DISPLAY_IMAGE_HEIGHT
    scale = DISPLAY_IMAGE_HEIGHT / image_height
    return max(1, round(image_width * scale)), DISPLAY_IMAGE_HEIGHT


def canvas_to_source(x, y, image_width, image_height):
    display_width, display_height = get_display_size(image_width, image_height)
    source_x = int(max(0, min(x / display_width * image_width, image_width)))
    source_y = int(max(0, min(y / display_height * image_height, image_height)))
    return source_x, source_y


def source_to_canvas(crop, image_width, image_height):
    display_width, display_height = get_display_size(image_width, image_height)
    x0, y0, x1, y1 = crop
    return [
        x0 / image_width * display_width,
        y0 / image_height * display_height,
        x1 / image_width * display_width,
        y1 / image_height * display_height,
    ]


def import_image(execroot, design, source_path):
    source = Path(source_path)
    managed_name = SUPPORTED_EXTENSIONS.get(source.suffix.lower())
    if not managed_name:
        raise ValueError("Unsupported image format.")
    design_path = ensure_design_folders(execroot, design)
    for old_name in SUPPORTED_EXTENSIONS.values():
        old_path = design_path / old_name
        if old_path.exists() and old_name != managed_name:
            old_path.unlink()
    destination = design_path / managed_name
    shutil.copy2(source, destination)
    with Image.open(destination) as image:
        width, height = image.size
    design["source-file-path"] = str(source)
    design["image-file"] = managed_name
    design["image-hash"] = file_sha256(destination)
    design["image-width"] = width
    design["image-height"] = height
    for aspect in ASPECTS.values():
        design[aspect["crop-key"]] = default_import_crop(width, height, aspect)
    return destination


def slice_design(execroot, design):
    image_path = get_managed_image_path(execroot, design)
    if not image_path or not image_path.exists():
        raise FileNotFoundError("No imported source image.")
    slices_path = get_slices_path(execroot, design["uuid"])
    slices_path.mkdir(parents=True, exist_ok=True)
    written = []
    with Image.open(image_path) as image:
        for mode, aspect in ASPECTS.items():
            crop = design[aspect["crop-key"]]
            if not crop:
                continue
            output = slices_path / f"{design['name']}_{aspect['filename-token']}.png"
            image.crop(tuple(crop)).save(output, "PNG")
            written.append(output)
    return written

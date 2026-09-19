from __future__ import annotations

import re
import subprocess
import sys
import json
import os
import random
import threading
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
import statistics
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageTk
from blythe_ai import (
    BACKGROUND_PROMPTS,
    COLOR_PROMPTS,
    DESIGN_PROMPTS,
    STYLE_PROMPTS,
    create_eye,
    create_eye_collection_16,
    design_collection_16,
)


DPI = 300
A4_WIDTH = 2480
A4_HEIGHT = 3508
SIX_BY_FOUR_WIDTH = 1800
SIX_BY_FOUR_HEIGHT = 1200
SIX_BY_FOUR_COLUMNS = 8
SIX_BY_FOUR_ROWS = 4
SIX_BY_FOUR_X0 = 190
SIX_BY_FOUR_Y0 = 230
SIX_BY_FOUR_X_PITCH = 200
SIX_BY_FOUR_Y_PITCH = 245
SIX_BY_FOUR_SOURCE_X_CENTERS = (188, 391, 599, 797, 999, 1203, 1393, 1591)
SIX_BY_FOUR_SOURCE_Y_CENTERS = (237, 473, 737, 971)
DEFAULT_DIAMETER_MM = 14.5
SIX_BY_FOUR_EYE_PX = 161
SIX_BY_FOUR_DIAMETER_MM = SIX_BY_FOUR_EYE_PX * 25.4 / DPI
DEFAULT_COLUMNS = 12
H_GAP = 28
V_GAP = 33
TOP_MARGIN = 89
BOTTOM_MARGIN = 80
CUT_LINE_GAP = 25
CUT_LINE_WIDTH = 2
CACHE_VERSION = 2
CACHE_DIR_NAME = "_prepared_14.5mm"
CACHE_MANIFEST_NAME = "prepared_manifest.json"
CACHE_STATUS_NAME = "สถานะไฟล์.txt"

# Modern white/green UI palette.
UI_BG = "#F5FAF7"
UI_SURFACE = "#FFFFFF"
UI_ACCENT = "#2BA66A"
UI_ACCENT_DARK = "#1E7E4E"
UI_ACCENT_SOFT = "#E4F6EC"
UI_TEXT = "#173D2B"
UI_MUTED = "#6B8477"
UI_BORDER = "#D6E9DE"

DEFAULT_SOURCE = Path.home() / "Dropbox" / "พีซี" / "ตาน้องบลาย" / "ขายเเบบ1"
DEFAULT_OUTPUT = DEFAULT_SOURCE.parent / "A4_ลูกค้า"
DEFAULT_SOURCE_4X6 = DEFAULT_SOURCE.parent / "ไฟล์ตา"
DEFAULT_OUTPUT_4X6 = DEFAULT_SOURCE.parent / "4x6_ลูกค้า"
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "BlytheA4Maker"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

VALID_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg", ".webp"}
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def design_key(group: int, design_id: str) -> str:
    """Internal key that keeps identical numbers from different sets separate."""
    return f"set{group}:{design_id}"


def display_design_id(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value


def second_source_folder(first_source: Path) -> Path:
    """Set 2 lives beside set 1 so moving the whole data folder keeps working."""
    return first_source.parent / "ขายเเบบ2"


def load_user_settings() -> dict[str, str]:
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_user_settings(settings: dict[str, str]) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = SETTINGS_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
    temp_file.replace(SETTINGS_FILE)


def natural_number_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def discover_assets(folder: Path) -> OrderedDict[str, Path]:
    """Find numbered assets. Prefer PSD when both PSD and PNG exist."""
    found: dict[str, Path] = {}
    if not folder.exists():
        return OrderedDict()

    extension_rank = {".psd": 0, ".png": 1, ".webp": 2, ".jpg": 3, ".jpeg": 4}
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in VALID_EXTENSIONS:
            continue
        if not NUMBER_RE.fullmatch(path.stem):
            continue

        old = found.get(path.stem)
        if old is None or extension_rank[path.suffix.lower()] < extension_rank[old.suffix.lower()]:
            found[path.stem] = path

    return OrderedDict(
        (key, found[key]) for key in sorted(found, key=natural_number_key)
    )



def four_sheet_sort_key(value: str) -> tuple[int, int, str]:
    numbers = re.findall(r"\d+", value)
    if numbers:
        return (0, int(numbers[0]), value.casefold())
    return (1, 10**9, value.casefold())


def discover_4x6_sheets(folder: Path) -> OrderedDict[str, Path]:
    """Find real 6x4-inch source sheets only. A4-sized images are ignored."""
    found: dict[str, Path] = {}
    if not folder.exists():
        return OrderedDict()

    extension_rank = {".png": 0, ".webp": 1, ".jpg": 2, ".jpeg": 3}
    for path in folder.iterdir():
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in extension_rank:
            continue
        try:
            with Image.open(path) as opened:
                if opened.size != (SIX_BY_FOUR_WIDTH, SIX_BY_FOUR_HEIGHT):
                    continue
        except OSError:
            continue
        old = found.get(path.stem)
        if old is None or extension_rank[suffix] < extension_rank[old.suffix.lower()]:
            found[path.stem] = path

    return OrderedDict((key, found[key]) for key in sorted(found, key=four_sheet_sort_key))


def four_pair_key(sheet_name: str, pair_index: int) -> str:
    return f"{sheet_name}::pair{pair_index}"


def _local_eye_center(
    source: Image.Image,
    approx_x: int,
    approx_y: int,
) -> tuple[int, int] | None:
    """Locate one eye inside its grid cell without changing its scale."""
    half_width = 100
    half_height = 110
    box = (
        max(0, approx_x - half_width),
        max(0, approx_y - half_height),
        min(source.width, approx_x + half_width + 1),
        min(source.height, approx_y + half_height + 1),
    )
    crop = source.crop(box)
    difference = ImageChops.difference(
        crop,
        Image.new("RGB", crop.size, "white"),
    ).convert("L")
    mask = difference.point(lambda value: 255 if value > 10 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return None

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    # Normal eye artwork in the source sheets is roughly 160 px across.
    # Reject large/odd artwork so a non-standard sheet cannot skew the grid.
    if min(width, height) < 110 or max(width, height) > 190:
        return None

    center_x = box[0] + round((bbox[0] + bbox[2]) / 2)
    center_y = box[1] + round((bbox[1] + bbox[3]) / 2)
    return center_x, center_y


@lru_cache(maxsize=128)
def _detect_4x6_centers_cached(
    path_text: str,
    mtime_ns: int,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    path = Path(path_text)
    with Image.open(path) as opened:
        source = flatten_to_white(opened)

    centers: list[tuple[tuple[int, int], ...]] = []
    for approx_y in SIX_BY_FOUR_SOURCE_Y_CENTERS:
        row_centers: list[tuple[int, int]] = []
        for approx_x in SIX_BY_FOUR_SOURCE_X_CENTERS:
            center = _local_eye_center(source, approx_x, approx_y)
            row_centers.append(center if center is not None else (approx_x, approx_y))
        centers.append(tuple(row_centers))
    return tuple(centers)


def detect_4x6_centers(
    path: Path,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return the actual center of each source eye; cache invalidates on file changes."""
    resolved = path.expanduser().resolve()
    return _detect_4x6_centers_cached(str(resolved), resolved.stat().st_mtime_ns)


def extract_4x6_pair(
    path: Path,
    pair_index: int,
    size_px: int | None = None,
) -> tuple[Image.Image, Image.Image]:
    """Copy one pair from its source sheet pixel-for-pixel at the original scale."""
    if pair_index < 1 or pair_index > 16:
        raise ValueError("คู่ตา 4x6 ต้องอยู่ระหว่าง 1-16")
    if size_px is None:
        size_px = SIX_BY_FOUR_EYE_PX

    with Image.open(path) as opened:
        source = flatten_to_white(opened)

    if source.size != (SIX_BY_FOUR_WIDTH, SIX_BY_FOUR_HEIGHT):
        raise ValueError(f"{path.name} ไม่ใช่ไฟล์ 6x4 นิ้ว 1800x1200")

    centers = detect_4x6_centers(path)
    row = (pair_index - 1) // 4
    pair_col = (pair_index - 1) % 4
    chips: list[Image.Image] = []

    for eye_col in (pair_col * 2, pair_col * 2 + 1):
        center_x, center_y = centers[row][eye_col]
        left = round(center_x - size_px / 2)
        top = round(center_y - size_px / 2)
        right = left + size_px
        bottom = top + size_px
        if left < 0 or top < 0 or right > source.width or bottom > source.height:
            raise ValueError(f"ตำแหน่งตาใน {path.name} อยู่นอกขอบไฟล์")
        chips.append(source.crop((left, top, right, bottom)))

    return chips[0], chips[1]


def extract_all_4x6_pairs(
    path: Path,
    size_px: int | None = None,
) -> list[tuple[Image.Image, Image.Image]]:
    if size_px is None:
        size_px = SIX_BY_FOUR_EYE_PX

    with Image.open(path) as opened:
        source = flatten_to_white(opened)

    if source.size != (SIX_BY_FOUR_WIDTH, SIX_BY_FOUR_HEIGHT):
        raise ValueError(f"{path.name} ไม่ใช่ไฟล์ 6x4 นิ้ว 1800x1200")

    centers = detect_4x6_centers(path)
    pairs: list[tuple[Image.Image, Image.Image]] = []
    for pair_index in range(1, 17):
        row = (pair_index - 1) // 4
        pair_col = (pair_index - 1) % 4
        pair_images: list[Image.Image] = []

        for eye_col in (pair_col * 2, pair_col * 2 + 1):
            center_x, center_y = centers[row][eye_col]
            left = round(center_x - size_px / 2)
            top = round(center_y - size_px / 2)
            right = left + size_px
            bottom = top + size_px
            if left < 0 or top < 0 or right > source.width or bottom > source.height:
                raise ValueError(f"ตำแหน่งตาใน {path.name} อยู่นอกขอบไฟล์")
            pair_images.append(source.crop((left, top, right, bottom)))

        pairs.append((pair_images[0], pair_images[1]))
    return pairs


def make_pair_ui_thumbnail(left: Image.Image, right: Image.Image) -> Image.Image:
    eye_size = 34
    gap = 4
    canvas = Image.new("RGBA", (eye_size * 2 + gap, eye_size), (0, 0, 0, 0))
    canvas.alpha_composite(make_round_ui_thumbnail(left, eye_size), (0, 0))
    canvas.alpha_composite(make_round_ui_thumbnail(right, eye_size), (eye_size + gap, 0))
    return canvas


def flatten_to_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    return background.convert("RGB")


def split_or_duplicate_pair(path: Path) -> tuple[Image.Image, Image.Image]:
    """Square files become an identical pair; obvious two-up files are split in half."""
    with Image.open(path) as opened:
        source = opened.convert("RGBA")

    width, height = source.size
    if width >= height * 1.70:
        midpoint = width // 2
        left = source.crop((0, 0, midpoint, height))
        right = source.crop((midpoint, 0, width, height))
        return flatten_to_white(left), flatten_to_white(right)

    single = flatten_to_white(source)
    return single.copy(), single.copy()


def visible_design_ids(assets: OrderedDict[str, Path]) -> list[str]:
    """Every source file gets its own button."""
    return list(assets)


def is_single_piece_id(design_id: str) -> bool:
    """Any dotted numbered filename is an individual eye piece."""
    return "." in design_id


def design_images(assets: OrderedDict[str, Path], design_id: str) -> list[Image.Image]:
    """Normal numbers make a pair; .1/.2 numbers make one piece."""
    path = assets.get(design_id)
    if path is None:
        raise ValueError(f"ไม่พบไฟล์หมายเลข {design_id}")
    left, right = split_or_duplicate_pair(path)
    return [left] if is_single_piece_id(design_id) else [left, right]


def make_chip(source: Image.Image, size_px: int) -> Image.Image:
    """Trim outer white canvas without cutting into the circular eye artwork."""
    rgb = source.convert("RGB")
    width, height = rgb.size

    # Ignore near-white canvas/anti-aliasing around the artwork.
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white"))
    content_mask = difference.convert("L").point(lambda value: 255 if value > 8 else 0)
    bbox = content_mask.getbbox()
    if bbox is not None:
        left, top, right, bottom = bbox
        box_width = right - left
        box_height = bottom - top
        # Eye chips are circular. Some designs contain white/pale decoration
        # that blends into the white canvas, so one detected axis can look
        # shorter than the real circle. Using the shorter axis clips those
        # designs. The longer axis is the safe diameter of the whole eye.
        side = max(box_width, box_height)
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2

        crop_left = round(center_x - side / 2)
        crop_top = round(center_y - side / 2)
        crop_right = crop_left + side
        crop_bottom = crop_top + side

        # Keep the crop square inside the source image.
        if crop_left < 0:
            crop_right -= crop_left
            crop_left = 0
        if crop_top < 0:
            crop_bottom -= crop_top
            crop_top = 0
        if crop_right > width:
            shift = crop_right - width
            crop_left -= shift
            crop_right = width
        if crop_bottom > height:
            shift = crop_bottom - height
            crop_top -= shift
            crop_bottom = height

        rgb = rgb.crop((crop_left, crop_top, crop_right, crop_bottom))

    fitted = ImageOps.fit(rgb, (size_px, size_px), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size_px, size_px), 0)
    tk_mask = Image.new("L", (size_px, size_px), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(tk_mask).ellipse((0, 0, size_px - 1, size_px - 1), fill=255)
    mask.paste(tk_mask)
    chip = Image.new("RGB", (size_px, size_px), "white")
    chip.paste(fitted, (0, 0), mask)
    return chip


def make_round_ui_thumbnail(source: Image.Image, size_px: int) -> Image.Image:
    """Create a transparent circular thumbnail for the GUI only."""
    resized = source.convert("RGBA").resize((size_px, size_px), Image.Resampling.LANCZOS)

    # Draw the alpha mask at higher resolution so the circular edge stays smooth.
    scale = 4
    mask_large = Image.new("L", (size_px * scale, size_px * scale), 0)
    from PIL import ImageDraw

    ImageDraw.Draw(mask_large).ellipse(
        (0, 0, size_px * scale - 1, size_px * scale - 1),
        fill=255,
    )
    alpha = mask_large.resize((size_px, size_px), Image.Resampling.LANCZOS)
    resized.putalpha(alpha)
    return resized


def diameter_to_pixels(diameter_mm: float) -> int:
    return max(1, round(diameter_mm / 25.4 * DPI))


def sanitize_filename(value: str) -> str:
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("._ ")


def source_signature(path: Path) -> dict[str, int | str]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def load_cache_manifest(cache_dir: Path) -> dict:
    manifest_path = cache_dir / CACHE_MANIFEST_NAME
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("version") != CACHE_VERSION:
            return {"version": CACHE_VERSION, "items": {}}
        return data
    except (OSError, ValueError, TypeError):
        return {"version": CACHE_VERSION, "items": {}}


def save_cache_manifest(cache_dir: Path, manifest: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / CACHE_MANIFEST_NAME
    temp_path = cache_dir / (CACHE_MANIFEST_NAME + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    temp_path.replace(manifest_path)


def prepare_asset_cache(
    assets: OrderedDict[str, Path],
    source_folder: Path,
) -> tuple[OrderedDict[str, tuple[Path, ...]], dict[str, object]]:
    """Prepare each source once and reuse it until that source file changes."""
    cache_dir = source_folder / CACHE_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_cache_manifest(cache_dir)
    old_items = manifest.get("items", {})
    new_items: dict[str, dict] = {}
    prepared: OrderedDict[str, tuple[Path, ...]] = OrderedDict()
    reused: list[str] = []
    rebuilt: list[str] = []
    failed: dict[str, str] = {}
    size_px = diameter_to_pixels(DEFAULT_DIAMETER_MM)

    for design_id, source_path in assets.items():
        signature = source_signature(source_path)
        old = old_items.get(design_id, {})
        old_piece_names = old.get("pieces", [])
        old_piece_paths = tuple(cache_dir / name for name in old_piece_names)
        cache_valid = (
            old.get("source") == signature
            and old.get("size_px") == size_px
            and bool(old_piece_paths)
            and all(path.exists() for path in old_piece_paths)
        )

        if cache_valid:
            prepared[design_id] = old_piece_paths
            new_items[design_id] = old
            reused.append(design_id)
            continue

        try:
            source_images = design_images(assets, design_id)
            piece_paths: list[Path] = []
            for piece_index, source_image in enumerate(source_images, start=1):
                chip = make_chip(source_image, size_px)
                safe_id = design_id.replace(".", "_")
                piece_path = cache_dir / f"{safe_id}__{piece_index}.png"
                chip.save(piece_path, format="PNG", dpi=(DPI, DPI))
                piece_paths.append(piece_path)

            item = {
                "source": signature,
                "size_px": size_px,
                "diameter_mm": DEFAULT_DIAMETER_MM,
                "pieces": [path.name for path in piece_paths],
            }
            prepared[design_id] = tuple(piece_paths)
            new_items[design_id] = item
            rebuilt.append(design_id)
        except Exception as exc:
            failed[design_id] = str(exc)

    manifest = {
        "version": CACHE_VERSION,
        "diameter_mm": DEFAULT_DIAMETER_MM,
        "dpi": DPI,
        "items": new_items,
    }
    save_cache_manifest(cache_dir, manifest)
    status_lines = [
        f"Blythe prepared cache • {DEFAULT_DIAMETER_MM} mm • {DPI} DPI",
        f"อัปเดตล่าสุด: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    reused_set = set(reused)
    rebuilt_set = set(rebuilt)
    for design_id in assets:
        if design_id in failed:
            status_lines.append(f"[ผิดพลาด] {design_id} : {failed[design_id]}")
        elif design_id in rebuilt_set:
            status_lines.append(f"[พร้อม-ทำใหม่] {design_id} <- {assets[design_id].name}")
        elif design_id in reused_set:
            status_lines.append(f"[พร้อม-ใช้เดิม] {design_id} <- {assets[design_id].name}")
    try:
        (cache_dir / CACHE_STATUS_NAME).write_text(
            "\n".join(status_lines) + "\n",
            encoding="utf-8-sig",
        )
    except OSError:
        pass
    return prepared, {
        "cache_dir": cache_dir,
        "reused": reused,
        "rebuilt": rebuilt,
        "failed": failed,
    }


def cached_design_chips(
    prepared_assets: OrderedDict[str, tuple[Path, ...]],
    design_id: str,
    size_px: int,
) -> list[Image.Image]:
    paths = prepared_assets.get(design_id)
    if not paths:
        raise ValueError(f"ยังไม่มีไฟล์พร้อมพิมพ์หมายเลข {design_id}")

    chips: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as opened:
            chip = opened.convert("RGB")
        if chip.size != (size_px, size_px):
            chip = chip.resize((size_px, size_px), Image.Resampling.LANCZOS)
        chips.append(chip)
    return chips


def prepare_a4_layout(
    assets: OrderedDict[str, Path],
    selections: OrderedDict[str, int],
    diameter_mm: float = DEFAULT_DIAMETER_MM,
    columns: int = DEFAULT_COLUMNS,
    prepared_assets: OrderedDict[str, tuple[Path, ...]] | None = None,
) -> tuple[list[Image.Image], int, int, int, int]:
    if diameter_mm <= 0:
        raise ValueError("ขนาดตาต้องมากกว่า 0 มม.")
    if columns <= 0:
        raise ValueError("จำนวนคอลัมน์ต้องมากกว่า 0")

    size_px = diameter_to_pixels(diameter_mm)
    content_width = columns * size_px + (columns - 1) * H_GAP
    if content_width > A4_WIDTH:
        raise ValueError("ขนาดตาหรือจำนวนคอลัมน์กว้างเกินหน้า A4")

    row_pitch = size_px + V_GAP
    usable_height = A4_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN
    rows = max(1, (usable_height + V_GAP) // row_pitch)
    capacity = rows * columns
    left_margin = (A4_WIDTH - content_width) // 2

    slots: list[Image.Image] = []
    for design_id, count in selections.items():
        if prepared_assets is not None and design_id in prepared_assets:
            chips = cached_design_chips(prepared_assets, design_id, size_px)
        else:
            chips = [make_chip(image, size_px) for image in design_images(assets, design_id)]
        for _ in range(count):
            slots.extend(chip.copy() for chip in chips)

    return slots, size_px, row_pitch, capacity, left_margin


def render_a4_page(
    assets: OrderedDict[str, Path],
    selections: OrderedDict[str, int],
    page_index: int = 0,
    diameter_mm: float = DEFAULT_DIAMETER_MM,
    columns: int = DEFAULT_COLUMNS,
    prepared_assets: OrderedDict[str, tuple[Path, ...]] | None = None,
) -> Image.Image:
    slots, size_px, row_pitch, capacity, left_margin = prepare_a4_layout(
        assets, selections, diameter_mm, columns, prepared_assets
    )
    page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
    start = page_index * capacity
    page_slots = slots[start : start + capacity]
    for index, chip in enumerate(page_slots):
        row, col = divmod(index, columns)
        x = left_margin + col * (size_px + H_GAP)
        y = TOP_MARGIN + row * row_pitch
        page.paste(chip, (x, y))

    if page_slots:
        from PIL import ImageDraw

        rows_used = (len(page_slots) + columns - 1) // columns
        last_row_bottom = TOP_MARGIN + (rows_used - 1) * row_pitch + size_px
        line_y = min(A4_HEIGHT - 1, last_row_bottom + CUT_LINE_GAP)
        ImageDraw.Draw(page).line(
            (0, line_y, A4_WIDTH - 1, line_y),
            fill="black",
            width=CUT_LINE_WIDTH,
        )
    return page


def build_a4_pages(
    assets: OrderedDict[str, Path],
    selections: OrderedDict[str, int],
    output_dir: Path,
    customer_name: str = "",
    diameter_mm: float = DEFAULT_DIAMETER_MM,
    columns: int = DEFAULT_COLUMNS,
    prepared_assets: OrderedDict[str, tuple[Path, ...]] | None = None,
) -> list[Path]:
    if not selections:
        raise ValueError("ยังไม่ได้เลือกหมายเลข")
    slots, _size_px, _row_pitch, capacity, _left_margin = prepare_a4_layout(
        assets, selections, diameter_mm, columns, prepared_assets
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(customer_name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"A4_{safe_name}_{stamp}" if safe_name else f"A4_{stamp}"

    page_count = (len(slots) + capacity - 1) // capacity
    outputs: list[Path] = []

    for page_index in range(page_count):
        page = render_a4_page(
            assets,
            selections,
            page_index,
            diameter_mm,
            columns,
            prepared_assets,
        )

        suffix = f"_p{page_index + 1}" if page_count > 1 else ""
        output = output_dir / f"{base_name}{suffix}.png"
        page.save(output, format="PNG", dpi=(DPI, DPI))
        outputs.append(output)

    return outputs




def prepare_4x6_layout(
    pair_refs: dict[str, tuple[Path, int]],
    selection_sequence: list[str],
    diameter_mm: float = SIX_BY_FOUR_DIAMETER_MM,
) -> tuple[list[Image.Image], int, int]:
    if diameter_mm <= 0:
        raise ValueError("ขนาดตาต้องมากกว่า 0 มม.")

    size_px = diameter_to_pixels(diameter_mm)
    if size_px > min(SIX_BY_FOUR_X_PITCH, SIX_BY_FOUR_Y_PITCH):
        raise ValueError("ขนาดตาใหญ่เกินกริด 4×6")

    slots: list[Image.Image] = []
    for pair_key in selection_sequence:
        ref = pair_refs.get(pair_key)
        if ref is None:
            raise ValueError(f"ไม่พบคู่ตา {pair_key}")
        path, pair_index = ref
        left, right = extract_4x6_pair(path, pair_index, size_px)
        slots.extend((left, right))

    return slots, size_px, SIX_BY_FOUR_COLUMNS * SIX_BY_FOUR_ROWS


def render_4x6_page(
    pair_refs: dict[str, tuple[Path, int]],
    selection_sequence: list[str],
    page_index: int = 0,
    diameter_mm: float = SIX_BY_FOUR_DIAMETER_MM,
) -> Image.Image:
    slots, size_px, capacity = prepare_4x6_layout(
        pair_refs, selection_sequence, diameter_mm
    )
    page = Image.new("RGB", (SIX_BY_FOUR_WIDTH, SIX_BY_FOUR_HEIGHT), "white")
    start = page_index * capacity
    page_slots = slots[start : start + capacity]
    radius = size_px / 2

    for index, chip in enumerate(page_slots):
        row, col = divmod(index, SIX_BY_FOUR_COLUMNS)
        center_x = SIX_BY_FOUR_SOURCE_X_CENTERS[col]
        center_y = SIX_BY_FOUR_SOURCE_Y_CENTERS[row]
        x = round(center_x - radius)
        y = round(center_y - radius)
        page.paste(chip, (x, y))

    return page


def build_4x6_pages(
    pair_refs: dict[str, tuple[Path, int]],
    selection_sequence: list[str],
    output_dir: Path,
    customer_name: str = "",
    diameter_mm: float = SIX_BY_FOUR_DIAMETER_MM,
) -> list[Path]:
    if not selection_sequence:
        raise ValueError("ยังไม่ได้เลือกคู่ตา")

    slots, _size_px, capacity = prepare_4x6_layout(
        pair_refs, selection_sequence, diameter_mm
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(customer_name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"4x6_{safe_name}_{stamp}" if safe_name else f"4x6_{stamp}"
    page_count = (len(slots) + capacity - 1) // capacity
    outputs: list[Path] = []

    for page_index in range(page_count):
        page = render_4x6_page(
            pair_refs,
            selection_sequence,
            page_index,
            diameter_mm,
        )
        suffix = f"_p{page_index + 1}" if page_count > 1 else ""
        output = output_dir / f"{base_name}{suffix}.png"
        page.save(output, format="PNG", dpi=(DPI, DPI))
        outputs.append(output)

    return outputs


def build_ai_preset_sheet(images: list[Image.Image], output_path: Path) -> Path:
    """Create one ready 4x6 source sheet: 16 pairs / 32 eyes at the real source size."""
    if len(images) != 16:
        raise ValueError("ชุด AI ต้องมี 16 คู่พอดี")

    page = Image.new("RGB", (SIX_BY_FOUR_WIDTH, SIX_BY_FOUR_HEIGHT), "white")
    for pair_index, source in enumerate(images):
        rgba = source.convert("RGBA")
        mask = rgba.getchannel("A").point(lambda value: 255 if value > 8 else 0)
        bbox = mask.getbbox()
        if bbox is None:
            raise ValueError(f"คู่ {pair_index + 1} ไม่มีรูปตาที่ใช้งานได้")
        eye = rgba.crop(bbox)
        scale = SIX_BY_FOUR_EYE_PX / max(eye.width, eye.height)
        eye = eye.resize(
            (max(1, round(eye.width * scale)), max(1, round(eye.height * scale))),
            Image.Resampling.LANCZOS,
        )
        chip = Image.new("RGBA", (SIX_BY_FOUR_EYE_PX, SIX_BY_FOUR_EYE_PX), (255, 255, 255, 0))
        chip.alpha_composite(
            eye,
            ((SIX_BY_FOUR_EYE_PX - eye.width) // 2, (SIX_BY_FOUR_EYE_PX - eye.height) // 2),
        )
        flat = Image.new("RGB", chip.size, "white")
        flat.paste(chip, (0, 0), chip)

        for slot_index in (pair_index * 2, pair_index * 2 + 1):
            row, col = divmod(slot_index, SIX_BY_FOUR_COLUMNS)
            center_x = SIX_BY_FOUR_SOURCE_X_CENTERS[col]
            center_y = SIX_BY_FOUR_SOURCE_Y_CENTERS[row]
            x = round(center_x - SIX_BY_FOUR_EYE_PX / 2)
            y = round(center_y - SIX_BY_FOUR_EYE_PX / 2)
            page.paste(flat, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(output_path, format="PNG", dpi=(DPI, DPI))
    return output_path

def selected_piece_count(selections: OrderedDict[str, int]) -> int:
    return sum(
        count * (1 if is_single_piece_id(display_design_id(design_id)) else 2)
        for design_id, count in selections.items()
    )

def parse_quick_numbers(text: str) -> list[str]:
    return [item for item in re.split(r"[\s,;/]+", text.strip()) if item]


class BlytheA4App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Blythe Eye Maker")
        self.geometry("760x560")
        self.minsize(680, 500)
        self.configure(bg=UI_BG)
        self._configure_theme()

        saved_settings = load_user_settings()
        saved_source = saved_settings.get("source_folder", "").strip()
        saved_source_4x6 = saved_settings.get("source_4x6_folder", "").strip()
        initial_source = Path(saved_source) if saved_source else DEFAULT_SOURCE
        initial_source_4x6 = (
            Path(saved_source_4x6)
            if saved_source_4x6
            else initial_source.parent / "ไฟล์ตา"
        )

        self.source_var = tk.StringVar(value=str(initial_source))
        self.source_4x6_var = tk.StringVar(value=str(initial_source_4x6))
        self.output_var = tk.StringVar(value=str(initial_source.parent / "A4_ลูกค้า"))
        self.output_4x6_var = tk.StringVar(value=str(initial_source_4x6.parent / "4x6_ลูกค้า"))
        self.customer_var = tk.StringVar()
        self.cache_var = tk.StringVar(value="กำลังตรวจไฟล์...")
        self.six_status_var = tk.StringVar(value="0 / 16 คู่")
        self.six_sheet_var = tk.StringVar()
        self.ai_status_var = tk.StringVar(value="พร้อมสร้าง")
        self.ai_style_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_background_var = tk.StringVar(value="โปร่งใส")
        self.ai_design_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_primary_color_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_secondary_color_var = tk.StringVar(value="อัตโนมัติ")
        self.current_page = "a4"

        self.assets: OrderedDict[str, Path] = OrderedDict()
        self.prepared_assets: OrderedDict[str, tuple[Path, ...]] = OrderedDict()
        self.cache_stats: dict[str, object] = {}
        self.design_ids: list[str] = []
        self.selections: OrderedDict[str, int] = OrderedDict()
        self.selection_history: list[str] = []
        self.number_buttons: dict[str, tk.Button] = {}
        self.thumbnails: dict[str, ImageTk.PhotoImage] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.six_sheets: OrderedDict[str, Path] = OrderedDict()
        self.six_pair_refs: OrderedDict[str, tuple[Path, int]] = OrderedDict()
        self.six_selections: OrderedDict[str, int] = OrderedDict()
        self.six_selection_history: list[str] = []
        self.six_number_buttons: dict[str, tk.Button] = {}
        self.six_thumbnails: dict[str, ImageTk.PhotoImage] = {}
        self.six_preview_photo: ImageTk.PhotoImage | None = None
        self.ai_image: Image.Image | None = None
        self.ai_image_path: Path | None = None
        self.ai_preview_photo: ImageTk.PhotoImage | None = None
        self.ai_collection_plan: dict | None = None
        self.ai_collection_state: dict[str, str] | None = None
        self.ai_collection_prompt = ""

        self._build_ui()
        source_a4_ok = Path(self.source_var.get()).is_dir()
        source_4x6_ok = Path(self.source_4x6_var.get()).is_dir()
        if source_a4_ok and source_4x6_ok:
            self.reload_assets()
        else:
            self.cache_var.set("ตั้งค่า Source ครั้งแรก")
            self.after(150, self.open_settings)

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_TEXT, font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=UI_BG, foreground=UI_MUTED, font=("Segoe UI", 8))
        style.configure(
            "TEntry",
            fieldbackground=UI_SURFACE,
            foreground=UI_TEXT,
            insertcolor=UI_TEXT,
            bordercolor=UI_BORDER,
            lightcolor=UI_BORDER,
            darkcolor=UI_BORDER,
            padding=5,
        )
        style.configure(
            "TButton",
            background=UI_SURFACE,
            foreground=UI_TEXT,
            bordercolor=UI_BORDER,
            lightcolor=UI_BORDER,
            darkcolor=UI_BORDER,
            relief="flat",
            padding=(8, 5),
            font=("Segoe UI", 9),
        )
        style.map(
            "TButton",
            background=[("pressed", UI_ACCENT_SOFT), ("active", UI_ACCENT_SOFT)],
            foreground=[("pressed", UI_ACCENT_DARK), ("active", UI_ACCENT_DARK)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=UI_ACCENT_SOFT,
            troughcolor=UI_BG,
            bordercolor=UI_BG,
            arrowcolor=UI_ACCENT_DARK,
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        info = ttk.Frame(outer)
        info.pack(fill="x")
        ttk.Label(info, text="ลูกค้า", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Entry(info, textvariable=self.customer_var, width=18).pack(side="left", padx=(5, 10))
        ttk.Label(info, textvariable=self.cache_var, style="Muted.TLabel").pack(side="left", padx=(10, 0))
        tk.Button(
            info,
            text="⚙",
            command=self.open_settings,
            width=2,
            relief="flat",
            font=("Segoe UI Symbol", 11),
            cursor="hand2",
            bd=0,
            bg=UI_BG,
            fg=UI_ACCENT_DARK,
            activebackground=UI_ACCENT_SOFT,
            activeforeground=UI_ACCENT_DARK,
            highlightthickness=0,
        ).pack(side="right")

        nav = tk.Frame(outer, bg=UI_BG)
        nav.pack(fill="x", pady=(7, 6))
        self.a4_nav_button = tk.Button(
            nav,
            text="A4",
            command=lambda: self._show_page("a4"),
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        self.a4_nav_button.pack(side="left")
        self.six_nav_button = tk.Button(
            nav,
            text="4×6 นิ้ว",
            command=lambda: self._show_page("4x6"),
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        self.six_nav_button.pack(side="left", padx=(4, 0))
        self.ai_nav_button = tk.Button(
            nav,
            text="AI สร้างตา",
            command=lambda: self._show_page("ai"),
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        self.ai_nav_button.pack(side="left", padx=(4, 0))

        self.page_host = ttk.Frame(outer)
        self.page_host.pack(fill="both", expand=True)
        self.a4_page = ttk.Frame(self.page_host)
        self.six_page = ttk.Frame(self.page_host)
        self.ai_page = ttk.Frame(self.page_host)
        self._build_a4_page(self.a4_page)
        self._build_4x6_page(self.six_page)
        self._build_ai_page(self.ai_page)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self._show_page("a4")

    def _build_a4_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        number_box = ttk.Frame(body)
        number_box.pack(side="left", fill="both", expand=True)

        self.number_canvas = tk.Canvas(number_box, highlightthickness=0, bg=UI_BG)
        scrollbar = ttk.Scrollbar(number_box, orient="vertical", command=self.number_canvas.yview)
        self.number_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.number_canvas.pack(side="left", fill="both", expand=True)
        self.number_grid = ttk.Frame(self.number_canvas)
        self.number_window = self.number_canvas.create_window((0, 0), window=self.number_grid, anchor="nw")
        self.number_grid.bind("<Configure>", self._update_scrollregion)
        self.number_canvas.bind("<Configure>", self._resize_number_grid)

        preview = ttk.Frame(body, padding=(8, 0, 0, 0))
        preview.pack(side="right", fill="y")
        ttk.Label(
            preview,
            text="A4  •  ตัวอย่าง",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack()
        self.preview_label = ttk.Label(preview, anchor="center")
        self.preview_label.pack(pady=(6, 8))
        ttk.Button(preview, text="ลบล่าสุด", command=self.undo_last_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="ล้างทั้งหมด", command=self.clear_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="โฟลเดอร์", command=self.open_output_folder).pack(fill="x", pady=(0, 8))
        tk.Button(
            preview,
            text="สร้าง A4",
            command=self.generate,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 12, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        ).pack(fill="x")

    def _build_4x6_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        number_box = ttk.Frame(body)
        number_box.pack(side="left", fill="both", expand=True)

        chooser = ttk.Frame(number_box)
        chooser.pack(fill="x", pady=(0, 6))
        ttk.Label(
            chooser,
            text="ไฟล์ 4×6",
            font=("Segoe UI", 9, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack(side="left")
        self.six_sheet_combo = ttk.Combobox(
            chooser,
            textvariable=self.six_sheet_var,
            state="readonly",
            width=28,
        )
        self.six_sheet_combo.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.six_sheet_combo.bind("<<ComboboxSelected>>", self._on_4x6_sheet_changed)

        self.six_number_canvas = tk.Canvas(number_box, highlightthickness=0, bg=UI_BG)
        scrollbar = ttk.Scrollbar(number_box, orient="vertical", command=self.six_number_canvas.yview)
        self.six_number_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.six_number_canvas.pack(side="left", fill="both", expand=True)
        self.six_number_grid = ttk.Frame(self.six_number_canvas)
        self.six_number_window = self.six_number_canvas.create_window(
            (0, 0), window=self.six_number_grid, anchor="nw"
        )
        self.six_number_grid.bind("<Configure>", self._update_4x6_scrollregion)
        self.six_number_canvas.bind("<Configure>", self._resize_4x6_number_grid)

        preview = ttk.Frame(body, padding=(8, 0, 0, 0))
        preview.pack(side="right", fill="y")
        ttk.Label(
            preview,
            text="6×4 นิ้ว  •  Custom",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack()
        self.six_preview_label = tk.Label(
            preview,
            bg="white",
            bd=1,
            relief="solid",
            highlightthickness=0,
        )
        self.six_preview_label.pack(pady=(6, 5))
        ttk.Label(preview, textvariable=self.six_status_var, style="Muted.TLabel").pack(pady=(0, 7))
        ttk.Button(preview, text="ลบล่าสุด", command=self.undo_last_4x6_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="ล้างทั้งหมด", command=self.clear_4x6_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="โฟลเดอร์", command=self.open_4x6_output_folder).pack(fill="x", pady=(0, 8))
        tk.Button(
            preview,
            text="สร้าง 4×6",
            command=self.generate_4x6,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 12, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        ).pack(fill="x")

    def _build_ai_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        form = ttk.Frame(body)
        form.grid(row=0, column=0, sticky="nsew", padx=(4, 16))

        options = ttk.Frame(form)
        options.pack(fill="x", pady=(0, 10))
        ttk.Label(options, text="สไตล์ภาพ", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.ai_style_combo = ttk.Combobox(
            options,
            textvariable=self.ai_style_var,
            values=list(STYLE_PROMPTS),
            state="readonly",
            width=22,
        )
        self.ai_style_combo.pack(side="left", padx=(6, 14))
        ttk.Label(options, text="พื้นหลังโปร่งใส", style="Muted.TLabel").pack(side="left")

        design_row = ttk.Frame(form)
        design_row.pack(fill="x", pady=(0, 10))
        ttk.Label(design_row, text="ลายม่านตา", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.ai_design_combo = ttk.Combobox(
            design_row,
            textvariable=self.ai_design_var,
            values=list(DESIGN_PROMPTS),
            state="readonly",
            width=24,
        )
        self.ai_design_combo.pack(side="left", padx=(6, 14))
        ttk.Button(design_row, text="สุ่มทั้งหมด", command=self.randomize_ai_options).pack(side="left")

        color_row = ttk.Frame(form)
        color_row.pack(fill="x", pady=(0, 10))
        ttk.Label(color_row, text="สีหลัก", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.ai_primary_color_combo = ttk.Combobox(
            color_row,
            textvariable=self.ai_primary_color_var,
            values=list(COLOR_PROMPTS),
            state="readonly",
            width=11,
        )
        self.ai_primary_color_combo.pack(side="left", padx=(6, 14))
        ttk.Label(color_row, text="สีรอง", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.ai_secondary_color_combo = ttk.Combobox(
            color_row,
            textvariable=self.ai_secondary_color_var,
            values=list(COLOR_PROMPTS),
            state="readonly",
            width=11,
        )
        self.ai_secondary_color_combo.pack(side="left", padx=(6, 0))

        ttk.Label(
            form,
            text="รายละเอียดเพิ่ม (ไม่ใส่ก็ได้)",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack(anchor="w")
        self.ai_prompt_text = tk.Text(
            form,
            height=3,
            wrap="word",
            bg=UI_SURFACE,
            fg=UI_TEXT,
            relief="solid",
            bd=1,
            font=("Segoe UI", 10),
        )
        self.ai_prompt_text.pack(fill="x", pady=(6, 10))

        self.ai_generate_button = tk.Button(
            form,
            text="สร้างรูปตา",
            command=self.generate_ai_eye,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=9,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        self.ai_generate_button.pack(fill="x")
        self.ai_preset_button = tk.Button(
            form,
            text="วางแผนชุด 16 คู่",
            command=self.generate_ai_preset,
            bg=UI_ACCENT_DARK,
            fg="white",
            activebackground=UI_ACCENT,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=9,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        self.ai_preset_button.pack(fill="x", pady=(6, 0))

        ttk.Label(
            form,
            text="แผนชุด 16 คู่",
            font=("Segoe UI", 9, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack(anchor="w", pady=(9, 4))
        self.ai_plan_text = tk.Text(
            form,
            height=9,
            wrap="word",
            bg=UI_SURFACE,
            fg=UI_TEXT,
            relief="solid",
            bd=1,
            font=("Segoe UI", 9),
            padx=7,
            pady=6,
            state="disabled",
        )
        self.ai_plan_text.pack(fill="both", expand=True)

        self.ai_generate_preset_button = tk.Button(
            form,
            text="สร้างตามแผน 16 คู่",
            command=self.generate_ai_preset_from_plan,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=9,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            state="disabled",
        )
        self.ai_generate_preset_button.pack(fill="x", pady=(6, 0))
        ttk.Label(form, textvariable=self.ai_status_var, style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )

        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky="n", padx=(0, 4))
        ttk.Label(
            preview,
            text="AI Preview",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack()
        self.ai_preview_label = tk.Label(
            preview,
            bg="white",
            bd=1,
            relief="solid",
            highlightthickness=0,
        )
        self.ai_preview_label.pack(pady=(6, 8))
        self._set_ai_preview(Image.new("RGBA", (240, 240), (255, 255, 255, 0)))
        ttk.Button(preview, text="เปิดโฟลเดอร์", command=self.open_ai_output_folder).pack(fill="x")

    def _set_ai_preview(self, image: Image.Image) -> None:
        preview = ImageOps.contain(image.convert("RGBA"), (216, 216), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (240, 240), (238, 238, 238, 255))
        draw = ImageDraw.Draw(canvas)
        tile = 16
        for y in range(0, 240, tile):
            for x in range(0, 240, tile):
                if (x // tile + y // tile) % 2:
                    draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(255, 255, 255, 255))
        canvas.alpha_composite(preview, ((240 - preview.width) // 2, (240 - preview.height) // 2))
        self.ai_preview_photo = ImageTk.PhotoImage(canvas)
        self.ai_preview_label.configure(image=self.ai_preview_photo)

    def output_ai_dir(self) -> Path:
        return Path(self.source_var.get()).parent / "AI_Eyes"

    def open_ai_output_folder(self) -> None:
        folder = self.output_ai_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def randomize_ai_options(self) -> None:
        styles = [value for value in STYLE_PROMPTS if value != "อัตโนมัติ"]
        designs = [value for value in DESIGN_PROMPTS if value != "อัตโนมัติ"]
        colors = [value for value in COLOR_PROMPTS if value != "อัตโนมัติ"]
        self.ai_style_var.set(random.choice(styles))
        self.ai_design_var.set(random.choice(designs))
        primary, secondary = random.sample(colors, 2)
        self.ai_primary_color_var.set(primary)
        self.ai_secondary_color_var.set(secondary)
        self.ai_status_var.set("สุ่มตัวเลือกแล้ว")

    def _set_ai_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.ai_generate_button.configure(state=state)
        self.ai_preset_button.configure(state=state)
        self.ai_generate_preset_button.configure(
            state=("disabled" if busy or self.ai_collection_plan is None else "normal")
        )

    def generate_ai_eye(self) -> None:
        prompt = self.ai_prompt_text.get("1.0", "end").strip()
        style = self.ai_style_var.get()
        background = self.ai_background_var.get()
        design = self.ai_design_var.get()
        color_primary = self.ai_primary_color_var.get()
        color_secondary = self.ai_secondary_color_var.get()
        self._set_ai_busy(True)
        self.ai_status_var.set("กำลังสร้างรูป...")
        threading.Thread(
            target=self._generate_ai_eye_worker,
            args=(prompt, style, background, design, color_primary, color_secondary),
            daemon=True,
        ).start()

    def _generate_ai_eye_worker(
        self,
        prompt: str,
        style: str,
        background: str,
        design: str,
        color_primary: str,
        color_secondary: str,
    ) -> None:
        try:
            path, image = create_eye(
                prompt,
                self.output_ai_dir(),
                style=style,
                background=background,
                design=design,
                color_primary=color_primary,
                color_secondary=color_secondary,
            )
        except Exception as exc:
            self.after(0, self._finish_ai_eye_error, str(exc))
            return
        self.after(0, self._finish_ai_eye_success, path, image)

    def _finish_ai_eye_success(self, path: Path, image: Image.Image) -> None:
        self.ai_image_path = path
        self.ai_image = image
        self._set_ai_preview(image)
        self.ai_status_var.set(f"สร้างเสร็จ: {path.name}")
        self._set_ai_busy(False)

    def _finish_ai_eye_error(self, message: str) -> None:
        self.ai_status_var.set("สร้างรูปไม่สำเร็จ")
        self._set_ai_busy(False)
        messagebox.showerror("AI สร้างตา", message)

    def generate_ai_preset(self) -> None:
        prompt = self.ai_prompt_text.get("1.0", "end").strip()
        style = self.ai_style_var.get()
        design = self.ai_design_var.get()
        color_primary = self.ai_primary_color_var.get()
        color_secondary = self.ai_secondary_color_var.get()
        self.ai_collection_plan = None
        self.ai_collection_prompt = prompt
        self._show_ai_plan_text("")
        self._set_ai_busy(True)
        self.ai_status_var.set("กำลังวางแผนชุด 16 คู่...")
        threading.Thread(
            target=self._plan_ai_preset_worker,
            args=(
                prompt,
                style,
                design,
                color_primary,
                color_secondary,
                self.ai_collection_state,
            ),
            daemon=True,
        ).start()

    def _plan_ai_preset_worker(
        self,
        prompt: str,
        style: str,
        design: str,
        color_primary: str,
        color_secondary: str,
        conversation_state: dict[str, str] | None,
    ) -> None:
        try:
            plan, conversation_state = design_collection_16(
                prompt,
                style=style,
                design=design,
                color_primary=color_primary,
                color_secondary=color_secondary,
                conversation_state=conversation_state,
            )
        except Exception as exc:
            self.after(0, self._finish_ai_eye_error, str(exc))
            return
        self.after(0, self._finish_ai_plan_success, plan, conversation_state, prompt)

    def _format_ai_plan(self, plan: dict) -> str:
        lines = [
            f"ชื่อชุด: {plan.get('collection_name', '')}",
            f"คอนเซ็ปต์: {plan.get('concept', '')}",
            f"แนวทาง: {plan.get('direction', '')}",
            f"สไตล์: {plan.get('style', '')}  •  ลาย: {plan.get('design', '')}",
            "",
        ]
        for item in plan.get("pairs", []):
            lines.append(
                f"{int(item['index']):02d}. {item['primary']} + {item['secondary']} — {item.get('variation', '')}"
            )
        return "\n".join(lines)

    def _show_ai_plan_text(self, text: str) -> None:
        self.ai_plan_text.configure(state="normal")
        self.ai_plan_text.delete("1.0", "end")
        if text:
            self.ai_plan_text.insert("1.0", text)
        self.ai_plan_text.configure(state="disabled")

    def _finish_ai_plan_success(
        self,
        plan: dict,
        conversation_state: dict[str, str],
        prompt: str,
    ) -> None:
        self.ai_collection_plan = plan
        self.ai_collection_state = conversation_state
        self.ai_collection_prompt = prompt
        self._show_ai_plan_text(self._format_ai_plan(plan))
        self.ai_status_var.set("แผนพร้อม • 16 คู่ • conversation เดียว")
        self._set_ai_busy(False)

    def generate_ai_preset_from_plan(self) -> None:
        if self.ai_collection_plan is None or self.ai_collection_state is None:
            self.ai_status_var.set("กรุณาวางแผนชุดก่อน")
            return
        self._set_ai_busy(True)
        self.ai_status_var.set("กำลังสร้าง 1/16...")
        threading.Thread(
            target=self._generate_ai_preset_worker,
            args=(
                self.ai_collection_plan,
                self.ai_collection_state,
                self.ai_collection_prompt,
                self.output_ai_dir(),
                Path(self.source_4x6_var.get()),
            ),
            daemon=True,
        ).start()

    def _generate_ai_preset_worker(
        self,
        plan: dict,
        conversation_state: dict[str, str],
        prompt: str,
        output_root: Path,
        source_4x6: Path,
    ) -> None:
        def progress(message: str) -> None:
            self.after(0, self.ai_status_var.set, message)

        def on_image(index: int, path: Path, image: Image.Image) -> None:
            preview = image.copy()
            self.after(0, self._show_ai_generation_progress, index, path, preview)

        try:
            preset_dir, paths, images = create_eye_collection_16(
                plan,
                prompt,
                output_root,
                conversation_state,
                progress=progress,
                on_image=on_image,
            )
            progress("กำลังจัดหน้า 4×6...")
            safe_name = sanitize_filename(str(plan.get("collection_name") or "AI_Preset")) or "AI_Preset"
            stamp = preset_dir.name.removeprefix("Preset_")
            sheet_path = source_4x6 / f"AI_Preset_{safe_name}_{stamp}.png"
            build_ai_preset_sheet(images, sheet_path)
        except Exception as exc:
            self.after(0, self._finish_ai_eye_error, str(exc))
            return
        self.after(
            0,
            self._finish_ai_preset_success,
            sheet_path,
            preset_dir,
            paths[-1],
            images[-1],
        )

    def _show_ai_generation_progress(self, index: int, path: Path, image: Image.Image) -> None:
        self.ai_image_path = path
        self.ai_image = image
        self._set_ai_preview(image)
        self.ai_status_var.set(f"กำลังสร้าง {index}/16 • conversation เดียว")

    def _finish_ai_preset_success(
        self,
        sheet_path: Path,
        preset_dir: Path,
        last_path: Path,
        last_image: Image.Image,
    ) -> None:
        self.ai_image_path = last_path
        self.ai_image = last_image
        self._set_ai_preview(last_image)
        self.ai_status_var.set(f"ชุด 16 คู่พร้อม • {preset_dir.name}")
        self._set_ai_busy(False)

        self.reload_4x6_assets()
        if sheet_path.stem in self.six_sheets:
            self.six_sheet_var.set(sheet_path.stem)
            self._populate_4x6_pair_grid()
            keys = [four_pair_key(sheet_path.stem, index) for index in range(1, 17)]
            self.six_selections = OrderedDict((key, 1) for key in keys)
            self.six_selection_history = keys
            self.refresh_4x6_selection_status()
            self.show_4x6_preview()

    def _show_page(self, page: str) -> None:
        self.current_page = page
        self.a4_page.pack_forget()
        self.six_page.pack_forget()
        self.ai_page.pack_forget()
        active_bg = UI_ACCENT
        inactive_bg = UI_SURFACE
        if page == "ai":
            self.ai_page.pack(fill="both", expand=True)
            self.a4_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.six_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.ai_nav_button.configure(bg=active_bg, fg="white")
        elif page == "4x6":
            self.six_page.pack(fill="both", expand=True)
            self.a4_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.six_nav_button.configure(bg=active_bg, fg="white")
            self.ai_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.show_4x6_preview()
        else:
            self.a4_page.pack(fill="both", expand=True)
            self.a4_nav_button.configure(bg=active_bg, fg="white")
            self.six_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.ai_nav_button.configure(bg=inactive_bg, fg=UI_TEXT)
            self.show_preview()

    def _on_mousewheel(self, event) -> None:
        canvas = self.six_number_canvas if self.current_page == "4x6" else self.number_canvas
        canvas.yview_scroll(int(-event.delta / 120), "units")

    def _update_scrollregion(self, _event=None) -> None:
        self.number_canvas.configure(scrollregion=self.number_canvas.bbox("all"))

    def _resize_number_grid(self, event) -> None:
        self.number_canvas.itemconfigure(self.number_window, width=event.width)

    def _update_4x6_scrollregion(self, _event=None) -> None:
        self.six_number_canvas.configure(scrollregion=self.six_number_canvas.bbox("all"))

    def _resize_4x6_number_grid(self, event) -> None:
        self.six_number_canvas.itemconfigure(self.six_number_window, width=event.width)

    def choose_source(self) -> None:
        current = Path(self.source_var.get()) if self.source_var.get() else DEFAULT_SOURCE
        initial = current if current.exists() else Path.home()
        folder = filedialog.askdirectory(initialdir=str(initial), title="เลือกโฟลเดอร์ลายตา")
        if folder:
            self.set_source_folder(Path(folder))

    def _save_source_settings(self) -> None:
        save_user_settings(
            {
                "source_folder": self.source_var.get(),
                "source_4x6_folder": self.source_4x6_var.get(),
            }
        )

    def set_source_folder(self, folder: Path, persist: bool = True) -> None:
        folder = folder.expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            messagebox.showwarning("ไม่พบโฟลเดอร์", "กรุณาเลือกโฟลเดอร์ A4 Source ที่มีอยู่จริง")
            return

        self.source_var.set(str(folder))
        self.output_var.set(str(folder.parent / "A4_ลูกค้า"))
        if persist:
            try:
                self._save_source_settings()
            except OSError as exc:
                messagebox.showwarning("บันทึกการตั้งค่าไม่ได้", str(exc))
        self.reload_assets()

    def set_4x6_source_folder(self, folder: Path, persist: bool = True) -> None:
        folder = folder.expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            messagebox.showwarning("ไม่พบโฟลเดอร์", "กรุณาเลือกโฟลเดอร์ 4×6 Source ที่มีอยู่จริง")
            return

        self.source_4x6_var.set(str(folder))
        self.output_4x6_var.set(str(folder.parent / "4x6_ลูกค้า"))
        if persist:
            try:
                self._save_source_settings()
            except OSError as exc:
                messagebox.showwarning("บันทึกการตั้งค่าไม่ได้", str(exc))
        self.reload_4x6_assets()

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("ตั้งค่า")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=UI_BG)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        a4_var = tk.StringVar(value=self.source_var.get())
        six_var = tk.StringVar(value=self.source_4x6_var.get())

        ttk.Label(frame, text="Source A4  •  ขายแบบ1", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            frame,
            text="โปรแกรมจะอ่านโฟลเดอร์ขายแบบ2 ที่อยู่ข้างกันให้อัตโนมัติ",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 5))
        ttk.Entry(frame, textvariable=a4_var, width=54).grid(row=2, column=0, sticky="ew", pady=(0, 10))

        def browse_into(target: tk.StringVar, title: str) -> None:
            current = Path(target.get()) if target.get() else Path.home()
            initial = current if current.exists() else Path.home()
            selected = filedialog.askdirectory(parent=dialog, initialdir=str(initial), title=title)
            if selected:
                target.set(selected)

        ttk.Button(
            frame,
            text="เลือก...",
            command=lambda: browse_into(a4_var, "เลือกโฟลเดอร์ Source A4"),
        ).grid(row=2, column=1, padx=(6, 0), pady=(0, 10))

        ttk.Label(frame, text="Source 4×6  •  ไฟล์ตา", font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text="โฟลเดอร์ไฟล์ตา 1800×1200 สำหรับหน้าคัสตอม", style="Muted.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 6)
        )
        ttk.Entry(frame, textvariable=six_var, width=54).grid(row=5, column=0, sticky="ew")
        ttk.Button(
            frame,
            text="เลือก...",
            command=lambda: browse_into(six_var, "เลือกโฟลเดอร์ Source 4×6"),
        ).grid(row=5, column=1, padx=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="ยกเลิก", command=dialog.destroy).pack(side="left", padx=(0, 6))

        def save_and_close() -> None:
            a4_value = a4_var.get().strip()
            six_value = six_var.get().strip()
            a4_folder = Path(a4_value).expanduser()
            six_folder = Path(six_value).expanduser()
            if not a4_value or not a4_folder.is_dir():
                messagebox.showwarning("ไม่พบโฟลเดอร์", "Source A4 ไม่ถูกต้อง", parent=dialog)
                return
            if not six_value or not six_folder.is_dir():
                messagebox.showwarning("ไม่พบโฟลเดอร์", "Source 4×6 ไม่ถูกต้อง", parent=dialog)
                return

            self.source_var.set(str(a4_folder.resolve()))
            self.source_4x6_var.set(str(six_folder.resolve()))
            self.output_var.set(str(a4_folder.resolve().parent / "A4_ลูกค้า"))
            self.output_4x6_var.set(str(six_folder.resolve().parent / "4x6_ลูกค้า"))
            try:
                self._save_source_settings()
            except OSError as exc:
                messagebox.showwarning("บันทึกการตั้งค่าไม่ได้", str(exc), parent=dialog)

            dialog.grab_release()
            dialog.destroy()
            self.reload_assets()

        ttk.Button(buttons, text="บันทึก", command=save_and_close).pack(side="left")
        frame.columnconfigure(0, weight=1)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")

    def reload_assets(self) -> None:
        folder = Path(self.source_var.get())
        folder2 = second_source_folder(folder)

        source_assets_1 = discover_assets(folder)
        prepared_1, stats_1 = prepare_asset_cache(source_assets_1, folder)

        source_assets_2 = discover_assets(folder2)
        if source_assets_2:
            prepared_2, stats_2 = prepare_asset_cache(source_assets_2, folder2)
        else:
            prepared_2 = OrderedDict()
            stats_2 = {"reused": [], "rebuilt": [], "failed": {}}

        ids_1 = [
            design_id
            for design_id in visible_design_ids(source_assets_1)
            if design_id in prepared_1
        ]
        ids_2 = [
            design_id
            for design_id in visible_design_ids(source_assets_2)
            if design_id in prepared_2
        ]

        self.assets = OrderedDict()
        self.prepared_assets = OrderedDict()
        self.design_ids = []
        group_ids: dict[int, list[str]] = {1: [], 2: []}
        for group, source_assets, prepared, raw_ids in (
            (1, source_assets_1, prepared_1, ids_1),
            (2, source_assets_2, prepared_2, ids_2),
        ):
            for raw_id in raw_ids:
                key = design_key(group, raw_id)
                self.assets[key] = source_assets[raw_id]
                self.prepared_assets[key] = prepared[raw_id]
                self.design_ids.append(key)
                group_ids[group].append(key)

        self.cache_stats = {
            "reused": list(stats_1.get("reused", [])) + list(stats_2.get("reused", [])),
            "rebuilt": list(stats_1.get("rebuilt", [])) + list(stats_2.get("rebuilt", [])),
            "failed": {
                **dict(stats_1.get("failed", {})),
                **{f"แบบ2:{key}": value for key, value in dict(stats_2.get("failed", {})).items()},
            },
        }

        self.selections.clear()
        self.selection_history.clear()
        for child in self.number_grid.winfo_children():
            child.destroy()
        self.number_buttons.clear()
        self.thumbnails.clear()

        columns = 6

        def add_design_button(design_id: str, row: int, col: int) -> None:
            try:
                preview_source = cached_design_chips(
                    self.prepared_assets,
                    design_id,
                    diameter_to_pixels(DEFAULT_DIAMETER_MM),
                )[0]
                preview = make_round_ui_thumbnail(preview_source, 46)
            except Exception:
                preview = Image.new("RGBA", (46, 46), (0, 0, 0, 0))

            photo = ImageTk.PhotoImage(preview)
            self.thumbnails[design_id] = photo
            button = tk.Button(
                self.number_grid,
                text=display_design_id(design_id),
                image=photo,
                compound="top",
                width=64,
                height=68,
                padx=1,
                pady=1,
                font=("Segoe UI", 8, "bold"),
                relief="flat",
                bd=0,
                bg=UI_SURFACE,
                fg=UI_TEXT,
                activebackground=UI_ACCENT_SOFT,
                activeforeground=UI_ACCENT_DARK,
                highlightthickness=1,
                highlightbackground=UI_BORDER,
                highlightcolor=UI_ACCENT,
                cursor="hand2",
                command=lambda value=design_id: self.select_and_add(value),
            )
            button.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
            button.bind("<Button-3>", lambda _event, value=design_id: self.select_and_remove(value))
            self.number_buttons[design_id] = button

        row_cursor = 0
        for index, design_id in enumerate(group_ids[1]):
            row_offset, col = divmod(index, columns)
            add_design_button(design_id, row_cursor + row_offset, col)

        if group_ids[1]:
            row_cursor += (len(group_ids[1]) + columns - 1) // columns

        if group_ids[2]:
            ttk.Label(
                self.number_grid,
                text="แบบที่สอง",
                font=("Segoe UI", 11, "bold"),
                foreground=UI_ACCENT_DARK,
            ).grid(
                row=row_cursor,
                column=0,
                columnspan=columns,
                sticky="w",
                padx=4,
                pady=(12, 6),
            )
            row_cursor += 1
            for index, design_id in enumerate(group_ids[2]):
                row_offset, col = divmod(index, columns)
                add_design_button(design_id, row_cursor + row_offset, col)

        for col in range(columns):
            self.number_grid.columnconfigure(col, weight=1)

        reused = len(self.cache_stats.get("reused", []))
        rebuilt = len(self.cache_stats.get("rebuilt", []))
        failed = len(self.cache_stats.get("failed", {}))
        cache_text = f"พร้อม {len(self.design_ids)} • เดิม {reused} • ทำใหม่ {rebuilt}"
        if failed:
            cache_text += f" • ผิดพลาด {failed}"
        self.cache_var.set(cache_text)

        self.refresh_selection_status()
        self.show_preview()
        if not self.design_ids:
            messagebox.showwarning("ไม่พบลายตา", f"ไม่พบไฟล์ที่ชื่อเป็นหมายเลขใน\n{folder}")

        self.reload_4x6_assets()

    def reload_4x6_assets(self) -> None:
        folder = Path(self.source_4x6_var.get())
        self.six_sheets = discover_4x6_sheets(folder)
        self.six_pair_refs = OrderedDict()
        for sheet_name, path in self.six_sheets.items():
            for pair_index in range(1, 17):
                self.six_pair_refs[four_pair_key(sheet_name, pair_index)] = (path, pair_index)

        self.six_selections.clear()
        self.six_selection_history.clear()
        values = list(self.six_sheets)
        self.six_sheet_combo.configure(values=values)

        if values:
            current = self.six_sheet_var.get()
            if current not in self.six_sheets:
                self.six_sheet_var.set(values[0])
            self._populate_4x6_pair_grid()
            self.six_status_var.set("0 / 16 คู่")
        else:
            self.six_sheet_var.set("")
            for child in self.six_number_grid.winfo_children():
                child.destroy()
            self.six_number_buttons.clear()
            self.six_thumbnails.clear()
            self.six_status_var.set("ไม่พบไฟล์ 6×4")

        self.show_4x6_preview()

    def _on_4x6_sheet_changed(self, _event=None) -> None:
        self._populate_4x6_pair_grid()

    def _populate_4x6_pair_grid(self) -> None:
        for child in self.six_number_grid.winfo_children():
            child.destroy()
        self.six_number_buttons.clear()
        self.six_thumbnails.clear()

        sheet_name = self.six_sheet_var.get()
        path = self.six_sheets.get(sheet_name)
        if path is None:
            return

        try:
            pairs = extract_all_4x6_pairs(path)
        except Exception as exc:
            self.six_status_var.set(f"อ่านไฟล์ไม่ได้: {exc}")
            return

        columns = 4
        for index, (left, right) in enumerate(pairs, start=1):
            key = four_pair_key(sheet_name, index)
            photo = ImageTk.PhotoImage(make_pair_ui_thumbnail(left, right))
            self.six_thumbnails[key] = photo
            count = self.six_selections.get(key, 0)
            button = tk.Button(
                self.six_number_grid,
                text=(f"คู่ {index}   ×{count}" if count else f"คู่ {index}"),
                image=photo,
                compound="top",
                width=90,
                height=62,
                padx=2,
                pady=2,
                font=("Segoe UI", 8, "bold"),
                relief="flat",
                bd=0,
                bg=UI_ACCENT_SOFT if count else UI_SURFACE,
                fg=UI_ACCENT_DARK if count else UI_TEXT,
                activebackground=UI_ACCENT_SOFT,
                activeforeground=UI_ACCENT_DARK,
                highlightthickness=1,
                highlightbackground=UI_ACCENT if count else UI_BORDER,
                highlightcolor=UI_ACCENT,
                cursor="hand2",
                command=lambda value=key: self.select_4x6_and_add(value),
            )
            row, col = divmod(index - 1, columns)
            button.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
            button.bind("<Button-3>", lambda _event, value=key: self.select_4x6_and_remove(value))
            self.six_number_buttons[key] = button

        for col in range(columns):
            self.six_number_grid.columnconfigure(col, weight=1)
        self.six_number_canvas.yview_moveto(0)
        self.refresh_4x6_selection_status()

    def show_preview(self, design_id: str | None = None) -> None:
        try:
            page = render_a4_page(
                self.assets,
                self.selections,
                prepared_assets=self.prepared_assets,
            )
            image = ImageOps.contain(page, (190, 269), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_photo)
        except Exception:
            pass

    def select_and_add(self, design_id: str) -> None:
        self.add_pair(design_id)
        self.show_preview(design_id)

    def select_and_remove(self, design_id: str) -> None:
        self.remove_pair(design_id)
        self.show_preview(design_id)

    def add_pair(self, design_id: str) -> None:
        self.selections[design_id] = self.selections.get(design_id, 0) + 1
        self.selection_history.append(design_id)
        self.refresh_selection_status()

    def remove_pair(self, design_id: str) -> None:
        count = self.selections.get(design_id, 0)
        if not count:
            return
        if count <= 1:
            self.selections.pop(design_id, None)
        else:
            self.selections[design_id] = count - 1
        for index in range(len(self.selection_history) - 1, -1, -1):
            if self.selection_history[index] == design_id:
                self.selection_history.pop(index)
                break
        self.refresh_selection_status()

    def undo_last_selection(self) -> None:
        if not self.selection_history:
            return
        design_id = self.selection_history.pop()
        count = self.selections.get(design_id, 0)
        if count <= 1:
            self.selections.pop(design_id, None)
        else:
            self.selections[design_id] = count - 1
        self.refresh_selection_status()
        self.show_preview(design_id)

    def clear_selection(self) -> None:
        self.selections.clear()
        self.selection_history.clear()
        self.refresh_selection_status()
        self.show_preview()

    def refresh_selection_status(self) -> None:
        for design_id, button in self.number_buttons.items():
            count = self.selections.get(design_id, 0)
            button.configure(
                text=(
                    f"{display_design_id(design_id)}   ×{count}"
                    if count
                    else display_design_id(design_id)
                ),
                relief="flat",
                bg=UI_ACCENT_SOFT if count else UI_SURFACE,
                fg=UI_ACCENT_DARK if count else UI_TEXT,
                highlightbackground=UI_ACCENT if count else UI_BORDER,
            )



    def show_4x6_preview(self, design_id: str | None = None) -> None:
        try:
            page = render_4x6_page(
                self.six_pair_refs,
                self.six_selection_history,
            )
            image = ImageOps.contain(page, (270, 180), Image.Resampling.LANCZOS)
            self.six_preview_photo = ImageTk.PhotoImage(image)
            self.six_preview_label.configure(image=self.six_preview_photo)
        except Exception:
            pass

    def select_4x6_and_add(self, design_id: str) -> None:
        if design_id not in self.six_pair_refs:
            return
        self.six_selections[design_id] = self.six_selections.get(design_id, 0) + 1
        self.six_selection_history.append(design_id)
        self.refresh_4x6_selection_status()
        self.show_4x6_preview(design_id)

    def select_4x6_and_remove(self, design_id: str) -> None:
        count = self.six_selections.get(design_id, 0)
        if not count:
            return
        if count <= 1:
            self.six_selections.pop(design_id, None)
        else:
            self.six_selections[design_id] = count - 1
        for index in range(len(self.six_selection_history) - 1, -1, -1):
            if self.six_selection_history[index] == design_id:
                self.six_selection_history.pop(index)
                break
        self.refresh_4x6_selection_status()
        self.show_4x6_preview(design_id)

    def undo_last_4x6_selection(self) -> None:
        if not self.six_selection_history:
            return
        design_id = self.six_selection_history.pop()
        count = self.six_selections.get(design_id, 0)
        if count <= 1:
            self.six_selections.pop(design_id, None)
        else:
            self.six_selections[design_id] = count - 1
        self.refresh_4x6_selection_status()
        self.show_4x6_preview(design_id)

    def clear_4x6_selection(self) -> None:
        self.six_selections.clear()
        self.six_selection_history.clear()
        self.refresh_4x6_selection_status()
        self.show_4x6_preview()

    def refresh_4x6_selection_status(self) -> None:
        for design_id, button in self.six_number_buttons.items():
            count = self.six_selections.get(design_id, 0)
            ref = self.six_pair_refs.get(design_id)
            pair_index = ref[1] if ref else "?"
            button.configure(
                text=(f"คู่ {pair_index}   ×{count}" if count else f"คู่ {pair_index}"),
                relief="flat",
                bg=UI_ACCENT_SOFT if count else UI_SURFACE,
                fg=UI_ACCENT_DARK if count else UI_TEXT,
                highlightbackground=UI_ACCENT if count else UI_BORDER,
            )

        pairs = len(self.six_selection_history)
        capacity = (SIX_BY_FOUR_COLUMNS * SIX_BY_FOUR_ROWS) // 2
        pages = max(1, (pairs + capacity - 1) // capacity)
        if pairs <= capacity:
            self.six_status_var.set(f"{pairs} / {capacity} คู่")
        else:
            self.six_status_var.set(f"{pairs} คู่  •  {pages} หน้า")

    def output_4x6_dir(self) -> Path:
        return Path(self.output_4x6_var.get())

    def open_4x6_output_folder(self) -> None:
        folder = self.output_4x6_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def generate_4x6(self) -> None:
        if not self.six_selection_history:
            messagebox.showwarning("ยังไม่ได้เลือก", "กรุณาเลือกคู่ตาจากไฟล์ 4×6 ก่อน")
            return

        try:
            outputs = build_4x6_pages(
                self.six_pair_refs,
                self.six_selection_history,
                self.output_4x6_dir(),
                customer_name=self.customer_var.get(),
                diameter_mm=SIX_BY_FOUR_DIAMETER_MM,
            )
        except Exception as exc:
            messagebox.showerror("สร้างไฟล์ไม่สำเร็จ", str(exc))
            return

        messagebox.showinfo(
            "สร้างเสร็จแล้ว",
            f"สร้าง {len(outputs)} ไฟล์ 4×6 แล้ว\n\n" + "\n".join(str(path) for path in outputs),
        )

    def output_dir(self) -> Path:
        return Path(self.output_var.get())

    def open_output_folder(self) -> None:
        folder = self.output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def generate(self) -> None:
        if not self.selections:
            messagebox.showwarning("ยังไม่ได้เลือก", "กรุณาคลิกหมายเลขที่ลูกค้าเลือกก่อน")
            return

        try:
            outputs = build_a4_pages(
                self.assets,
                self.selections,
                self.output_dir(),
                customer_name=self.customer_var.get(),
                diameter_mm=DEFAULT_DIAMETER_MM,
                prepared_assets=self.prepared_assets,
            )
        except Exception as exc:
            messagebox.showerror("สร้างไฟล์ไม่สำเร็จ", str(exc))
            return

        messagebox.showinfo(
            "สร้างเสร็จแล้ว",
            f"สร้าง {len(outputs)} หน้า A4 แล้ว\n\n" + "\n".join(str(path) for path in outputs),
        )


if __name__ == "__main__":
    app = BlytheA4App()
    app.mainloop()

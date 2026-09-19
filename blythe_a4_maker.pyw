from __future__ import annotations

import re
import subprocess
import sys
import json
import os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageOps, ImageTk


DPI = 300
A4_WIDTH = 2480
A4_HEIGHT = 3508
DEFAULT_DIAMETER_MM = 14.5
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

DEFAULT_SOURCE = Path.home() / "Dropbox" / "พีซี" / "ตาน้องบลาย" / "ขายเเบบ1"
DEFAULT_OUTPUT = DEFAULT_SOURCE.parent / "A4_ลูกค้า"
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "BlytheA4Maker"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

VALID_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg", ".webp"}
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


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


def parse_quick_numbers(text: str) -> list[str]:
    return [item for item in re.split(r"[\s,;/]+", text.strip()) if item]


class BlytheA4App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Blythe Eye A4 Maker")
        self.geometry("760x560")
        self.minsize(680, 500)

        saved_settings = load_user_settings()
        saved_source = saved_settings.get("source_folder", "").strip()
        initial_source = Path(saved_source) if saved_source else DEFAULT_SOURCE

        self.source_var = tk.StringVar(value=str(initial_source))
        self.output_var = tk.StringVar(value=str(initial_source.parent / "A4_ลูกค้า"))
        self.customer_var = tk.StringVar()
        self.cache_var = tk.StringVar(value="กำลังตรวจไฟล์...")

        self.assets: OrderedDict[str, Path] = OrderedDict()
        self.prepared_assets: OrderedDict[str, tuple[Path, ...]] = OrderedDict()
        self.cache_stats: dict[str, object] = {}
        self.design_ids: list[str] = []
        self.selections: OrderedDict[str, int] = OrderedDict()
        self.selection_history: list[str] = []
        self.number_buttons: dict[str, tk.Button] = {}
        self.thumbnails: dict[str, ImageTk.PhotoImage] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None

        self._build_ui()
        if Path(self.source_var.get()).exists():
            self.reload_assets()
        else:
            self.cache_var.set("เลือกโฟลเดอร์ลายตาครั้งแรก")
            self.after(150, self.choose_source)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        info = ttk.Frame(outer)
        info.pack(fill="x")
        ttk.Label(info, text="ลูกค้า").pack(side="left")
        ttk.Entry(info, textvariable=self.customer_var, width=18).pack(side="left", padx=(5, 10))
        ttk.Label(info, text="A4  •  14.5 mm", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(info, textvariable=self.cache_var, font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))
        tk.Button(
            info,
            text="⚙",
            command=self.open_settings,
            width=2,
            relief="flat",
            font=("Segoe UI Symbol", 11),
            cursor="hand2",
            bd=0,
        ).pack(side="right")

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(6, 0))

        number_box = ttk.Frame(body)
        number_box.pack(side="left", fill="both", expand=True)

        self.number_canvas = tk.Canvas(number_box, highlightthickness=0)
        scrollbar = ttk.Scrollbar(number_box, orient="vertical", command=self.number_canvas.yview)
        self.number_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.number_canvas.pack(side="left", fill="both", expand=True)
        self.number_grid = ttk.Frame(self.number_canvas)
        self.number_window = self.number_canvas.create_window((0, 0), window=self.number_grid, anchor="nw")
        self.number_grid.bind("<Configure>", self._update_scrollregion)
        self.number_canvas.bind("<Configure>", self._resize_number_grid)
        self.number_canvas.bind_all(
            "<MouseWheel>",
            lambda event: self.number_canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

        preview = ttk.Frame(body, padding=(8, 0, 0, 0))
        preview.pack(side="right", fill="y")
        ttk.Label(preview, text="ตัวอย่าง", font=("Segoe UI", 10, "bold")).pack()
        self.preview_label = ttk.Label(preview, anchor="center")
        self.preview_label.pack(pady=(6, 8))
        ttk.Button(preview, text="ลบล่าสุด", command=self.undo_last_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="ล้างทั้งหมด", command=self.clear_selection).pack(fill="x", pady=(0, 4))
        ttk.Button(preview, text="โฟลเดอร์", command=self.open_output_folder).pack(fill="x", pady=(0, 8))
        tk.Button(
            preview,
            text="สร้าง A4",
            command=self.generate,
            bg="#2e9d52",
            fg="white",
            activebackground="#248243",
            activeforeground="white",
            font=("Segoe UI", 12, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            cursor="hand2",
        ).pack(fill="x")

    def _update_scrollregion(self, _event=None) -> None:
        self.number_canvas.configure(scrollregion=self.number_canvas.bbox("all"))

    def _resize_number_grid(self, event) -> None:
        self.number_canvas.itemconfigure(self.number_window, width=event.width)

    def choose_source(self) -> None:
        current = Path(self.source_var.get()) if self.source_var.get() else DEFAULT_SOURCE
        initial = current if current.exists() else Path.home()
        folder = filedialog.askdirectory(initialdir=str(initial), title="เลือกโฟลเดอร์ลายตา")
        if folder:
            self.set_source_folder(Path(folder))

    def set_source_folder(self, folder: Path, persist: bool = True) -> None:
        folder = folder.expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            messagebox.showwarning("ไม่พบโฟลเดอร์", "กรุณาเลือกโฟลเดอร์ Source Data ที่มีอยู่จริง")
            return

        self.source_var.set(str(folder))
        self.output_var.set(str(folder.parent / "A4_ลูกค้า"))
        if persist:
            try:
                save_user_settings({"source_folder": str(folder)})
            except OSError as exc:
                messagebox.showwarning("บันทึกการตั้งค่าไม่ได้", str(exc))
        self.reload_assets()

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("ตั้งค่า")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Source Data", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text="โฟลเดอร์ที่เก็บไฟล์ลายตา").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 8)
        )

        source_setting_var = tk.StringVar(value=self.source_var.get())
        entry = ttk.Entry(frame, textvariable=source_setting_var, width=54)
        entry.grid(row=2, column=0, sticky="ew")

        def browse() -> None:
            current = Path(source_setting_var.get()) if source_setting_var.get() else Path.home()
            initial = current if current.exists() else Path.home()
            selected = filedialog.askdirectory(
                parent=dialog,
                initialdir=str(initial),
                title="เลือกโฟลเดอร์ Source Data",
            )
            if selected:
                source_setting_var.set(selected)

        ttk.Button(frame, text="เลือก...", command=browse).grid(row=2, column=1, padx=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="ยกเลิก", command=dialog.destroy).pack(side="left", padx=(0, 6))

        def save_and_close() -> None:
            value = source_setting_var.get().strip()
            if not value:
                messagebox.showwarning("ยังไม่ได้เลือก", "กรุณาเลือกโฟลเดอร์ Source Data", parent=dialog)
                return
            folder = Path(value).expanduser()
            if not folder.exists() or not folder.is_dir():
                messagebox.showwarning("ไม่พบโฟลเดอร์", "โฟลเดอร์ที่เลือกไม่มีอยู่จริง", parent=dialog)
                return
            dialog.grab_release()
            dialog.destroy()
            self.set_source_folder(folder)

        ttk.Button(buttons, text="บันทึก", command=save_and_close).pack(side="left")
        frame.columnconfigure(0, weight=1)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        entry.focus_set()

    def reload_assets(self) -> None:
        folder = Path(self.source_var.get())
        self.assets = discover_assets(folder)
        self.prepared_assets, self.cache_stats = prepare_asset_cache(self.assets, folder)
        self.design_ids = [
            design_id
            for design_id in visible_design_ids(self.assets)
            if design_id in self.prepared_assets
        ]
        self.selections.clear()
        self.selection_history.clear()

        for child in self.number_grid.winfo_children():
            child.destroy()
        self.number_buttons.clear()
        self.thumbnails.clear()

        columns = 6
        for index, design_id in enumerate(self.design_ids):
            row, col = divmod(index, columns)
            try:
                preview_source = cached_design_chips(
                    self.prepared_assets,
                    design_id,
                    diameter_to_pixels(DEFAULT_DIAMETER_MM),
                )[0]
                preview = preview_source.resize((46, 46), Image.Resampling.LANCZOS)
            except Exception:
                preview = Image.new("RGB", (46, 46), "#eeeeee")

            photo = ImageTk.PhotoImage(preview)
            self.thumbnails[design_id] = photo
            button = tk.Button(
                self.number_grid,
                text=design_id,
                image=photo,
                compound="top",
                width=64,
                height=68,
                padx=1,
                pady=1,
                font=("Segoe UI", 8, "bold"),
                relief="raised",
                command=lambda value=design_id: self.select_and_add(value),
            )
            button.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
            button.bind("<Button-3>", lambda _event, value=design_id: self.select_and_remove(value))
            self.number_buttons[design_id] = button

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
                text=f"{design_id}   ×{count}" if count else design_id,
                relief="sunken" if count else "raised",
                bg="#d9f2e6" if count else "SystemButtonFace",
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

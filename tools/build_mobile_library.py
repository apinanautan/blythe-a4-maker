"""Build the small, ready-to-use eye library the iPhone app downloads.

The desktop library (the `data` branch) holds full-size PNG/PSD files, ~300 MB.
This turns it into exactly the chips the desktop prints with (made by the
desktop's own functions), plus 4x6 pairs and cover templates, and an index.json:

    python tools/build_mobile_library.py <data checkout> <output folder>
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"


def load_app():
    # The desktop module imports Tk; the library build only needs its image functions.
    for name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk", "tkinter.simpledialog",
                 "tkinterdnd2", "PIL.ImageTk"):
        sys.modules.setdefault(name, mock.MagicMock())

    class _Tk:  # BlytheA4App subclasses TkinterDnD.Tk
        pass

    sys.modules["tkinterdnd2"].TkinterDnD.Tk = _Tk
    import PIL

    PIL.ImageTk = sys.modules["PIL.ImageTk"]
    sys.path.insert(0, str(APP_DIR))
    loader = importlib.machinery.SourceFileLoader("blythe_app", str(APP_DIR / "blythe_a4_maker.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


SETS = (
    ("set1", "แบบที่หนึ่ง", "a4_set1"),
    ("set2", "แบบที่สอง", "a4_set2"),
    ("set4", "คัสตอม", "custom"),
)


def build(data_dir: Path, out: Path) -> dict:
    app = load_app()
    a4_px = app.diameter_to_pixels(app.DEFAULT_DIAMETER_MM)
    six_px = app.SIX_BY_FOUR_EYE_PX
    out.mkdir(parents=True, exist_ok=True)
    index: dict = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": app.APP_VERSION,
        "layout": {
            "dpi": app.DPI,
            "a4": {"width": app.A4_WIDTH, "height": app.A4_HEIGHT, "chip": a4_px, "columns": app.DEFAULT_COLUMNS,
                   "h_gap": app.H_GAP, "v_gap": app.V_GAP, "top": app.TOP_MARGIN, "bottom": app.BOTTOM_MARGIN,
                   "cut_gap": app.CUT_LINE_GAP, "cut_width": app.CUT_LINE_WIDTH},
            "six": {"width": app.SIX_BY_FOUR_WIDTH, "height": app.SIX_BY_FOUR_HEIGHT, "chip": six_px,
                    "x_centers": list(app.SIX_BY_FOUR_SOURCE_X_CENTERS),
                    "y_centers": list(app.SIX_BY_FOUR_SOURCE_Y_CENTERS)},
            "cover": {"size": app.COVER_CANVAS_SIZE},
        },
        "sets": [],
        "sheets": [],
        "covers": [],
    }

    # Eye designs: one two-up PNG per design (left|right), or one chip for a single piece (e.g. 52.1).
    for key, title, folder_name in SETS:
        folder = data_dir / folder_name
        assets = app.discover_assets(folder)
        items = []
        target = out / "chips" / key
        target.mkdir(parents=True, exist_ok=True)
        for design_id in assets:
            try:
                chips = [app.make_chip(image, a4_px) for image in app.design_images(assets, design_id)]
            except Exception as exc:  # a broken file must not stop the whole library
                print(f"skip {folder_name}/{design_id}: {exc}")
                continue
            sheet = Image.new("RGB", (a4_px * len(chips), a4_px), "white")
            for position, chip in enumerate(chips):
                sheet.paste(chip, (position * a4_px, 0))
            name = f"{design_id}.png"
            sheet.save(target / name, optimize=True)
            label = f"คัส {design_id}" if key == "set4" else design_id
            items.append({"id": f"{key}:{design_id}", "label": label, "pieces": len(chips),
                          "file": f"chips/{key}/{name}"})
        index["sets"].append({"key": key, "title": title, "items": items})
        print(f"{title}: {len(items)}")

    # 4x6 sheets: the 32 eyes as an 8x4 grid of chips, cut exactly like the desktop does.
    sheets = app.discover_4x6_sheets(data_dir / "sheets_4x6")
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    for number, (name, path) in enumerate(sheets.items(), start=1):
        grid = Image.new("RGB", (six_px * 8, six_px * 4), "white")
        try:
            for pair in range(1, 17):
                left, right = app.extract_4x6_pair(path, pair, six_px)
                row, pair_col = (pair - 1) // 4, (pair - 1) % 4
                grid.paste(left, (pair_col * 2 * six_px, row * six_px))
                grid.paste(right, ((pair_col * 2 + 1) * six_px, row * six_px))
        except Exception as exc:
            print(f"skip sheet {name}: {exc}")
            continue
        file = f"sheets/{number:03d}.jpg"
        grid.save(out / file, quality=92)
        index["sheets"].append({"name": name, "file": file})
    print(f"4x6 sheets: {len(index['sheets'])}")

    # Cover templates: the bundled ones plus AI covers from the library.
    (out / "covers").mkdir(parents=True, exist_ok=True)
    templates = app.load_cover_templates()
    templates.update(app.load_library_covers(data_dir / "covers"))
    for template_id, item in templates.items():
        with Image.open(item["path"]) as opened:
            image = app.flatten_to_white(opened).resize((app.COVER_CANVAS_SIZE,) * 2, Image.Resampling.LANCZOS)
        file = f"covers/{template_id}.jpg"
        image.save(out / file, quality=90)
        index["covers"].append({
            "id": template_id, "label": item["label"], "file": file,
            "left": list(item["left_center"]), "right": list(item["right_center"]), "eye": int(item["eye_size"]),
        })
    print(f"covers: {len(index['covers'])}")

    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]), Path(sys.argv[2]))

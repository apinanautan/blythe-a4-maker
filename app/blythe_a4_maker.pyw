from __future__ import annotations

import re
import subprocess
import sys
import json
import hashlib
import os
import random
import shutil
import tempfile
import threading
import urllib.request
import webbrowser
import zipfile
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
import statistics
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

from PIL import Image, ImageChops, ImageDraw, ImageGrab, ImageOps, ImageTk
from blythe_ai import (
    create_cover_template,
    BACKGROUND_PROMPTS,
    COLOR_PROMPTS,
    DESIGN_PROMPTS,
    STYLE_PROMPTS,
    create_eye,
    create_eye_collection_16,
    design_collection_16,
)
from customer_portal import CustomerPortal
import data_sync


DPI = 300
CUSTOMER_LINK_NTFY_URL = "https://ntfy.sh/BlytheEyes"
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
CUSTOM_A4_DIR_NAME = "_custom_a4"

# Modern white/green UI palette.
UI_BG = "#F5FAF7"
UI_SURFACE = "#FFFFFF"
UI_ACCENT = "#2BA66A"
CUSTOM_A4_CROP_PREVIEW_PX = 300
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
DATA_SYNC_STATE_FILE = SETTINGS_DIR / "data_sync_state.json"
TRASH_DIR = SETTINGS_DIR / "trash"
UPDATE_LOG_FILE = SETTINGS_DIR / "update.log"
TRASH_KEEP_DAYS = 7
# Where a fresh install keeps the eye library downloaded from GitHub and the customer output.
DEFAULT_DATA_ROOT = Path.home() / "Documents" / "Blythe Eye Maker"  # customer output (visible)
# The eye library lives inside the program (hidden) and syncs with GitHub.
LIBRARY_DIR = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())) / "BlytheA4Maker" / "library"
LIBRARY_SET1 = LIBRARY_DIR / "ขายเเบบ1"
LIBRARY_SET2 = LIBRARY_DIR / "ขายเเบบ2"
LIBRARY_4X6 = LIBRARY_DIR / "ไฟล์ตา"
ORDERS_DIR = DEFAULT_DATA_ROOT / "ออเดอร์"
LIBRARY_COVERS = LIBRARY_DIR / "ปก"
COVER_FILE_RE = re.compile(r"cover_(\d+)__L(\d+)x(\d+)_R(\d+)x(\d+)_S(\d+)")
GITHUB_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
GITHUB_DATA_URL = "https://github.com/apinanautan/blythe-a4-maker/tree/data"
APP_UPDATE_API_URL = "https://api.github.com/repos/apinanautan/blythe-a4-maker/commits/main"
APP_VERSION = "1.4.0"
APP_RELEASES_API_URL = "https://api.github.com/repos/apinanautan/blythe-a4-maker/releases"
APP_ASSET_ARCHIVE_NAME = "BlytheEyeMakerAssets.zip"
APP_EXECUTABLE_NAME = "BlytheEyeMaker.exe"
APP_RELEASE_ASSETS_DIR = SETTINGS_DIR / "release_assets"

COVER_CANVAS_SIZE = 1000
COVER_EYE_SIZE = 195
COVER_TEMPLATE_SCLERA_SIZE = 224
COVER_LEFT_EYE_POS = (198, 398)
COVER_RIGHT_EYE_POS = (650, 398)


def app_resource_path(*parts: str) -> Path:
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS).joinpath(*parts))
    if getattr(sys, "frozen", False) and parts and parts[0] == "cover_assets":
        candidates.append(APP_RELEASE_ASSETS_DIR.joinpath(*parts))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent.joinpath(*parts))
    candidates.append(Path(__file__).resolve().parent.joinpath(*parts))
    existing = next((path for path in candidates if path.exists()), None)
    if existing is not None:
        return existing
    if getattr(sys, "frozen", False) and parts and parts[0] == "cover_assets":
        return APP_RELEASE_ASSETS_DIR.joinpath(*parts)
    return candidates[-1]


COVER_BASE_PATH = app_resource_path("cover_assets", "doll_cover_base.png")
COVER_OVERLAY_PATH = app_resource_path("cover_assets", "doll_cover_overlay.png")
COVER_TEMPLATES_DIR = app_resource_path("cover_assets", "templates_gpt_blank")
COVER_TEMPLATES_MANIFEST = COVER_TEMPLATES_DIR / "manifest.json"

VALID_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg", ".webp"}
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def design_key(group: int, design_id: str) -> str:
    """Internal key that keeps identical numbers from different sets separate."""
    return f"set{group}:{design_id}"


def display_design_id(value: str) -> str:
    if value.startswith("custom:"):
        number = value.split(":", 1)[1]
        return f"คัส {int(number):02d}" if number.isdigit() else f"คัส {number}"
    return value.split(":", 1)[1] if ":" in value else value


def load_library_covers(folder: Path = LIBRARY_COVERS) -> OrderedDict[str, dict[str, object]]:
    """AI covers saved in the library; eye positions are stored in the file name so the PNG alone syncs."""
    covers: OrderedDict[str, dict[str, object]] = OrderedDict()
    if not folder.is_dir():
        return covers
    found = []
    for path in folder.glob("cover_*.png"):
        match = COVER_FILE_RE.fullmatch(path.stem)
        if match:
            found.append((int(match.group(1)), path, match))
    for number, path, match in sorted(found):
        template_id = f"ai{number:02d}"
        covers[template_id] = {
            "id": template_id,
            "title": "ปก AI",
            "label": f"AI {number:02d} • ปกใหม่",
            "path": path,
            "sclera_blank": True,
            "left_center": (int(match.group(2)), int(match.group(3))),
            "right_center": (int(match.group(4)), int(match.group(5))),
            "eye_size": int(match.group(6)),
        }
    return covers


def detect_blank_eyes(
    image: Image.Image,
    hints: tuple[tuple[int, int], tuple[int, int]],
) -> tuple[tuple[int, int], tuple[int, int], int] | None:
    """Find the two blank white eyeballs near the reference cover's eye positions."""
    rgb = image.convert("RGB").resize((COVER_CANVAS_SIZE, COVER_CANVAS_SIZE), Image.Resampling.LANCZOS)
    low = rgb.convert("L").point(lambda value: 255 if value >= 228 else 0)
    pale = rgb.convert("HSV").getchannel("S").point(lambda value: 255 if value <= 40 else 0)
    mask = ImageChops.multiply(low, pale)
    found = []
    for hint_x, hint_y in hints:
        seed = None
        for radius in range(0, 60, 4):
            for dx, dy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
                x, y = hint_x + dx, hint_y + dy
                if 0 <= x < COVER_CANVAS_SIZE and 0 <= y < COVER_CANVAS_SIZE and mask.getpixel((x, y)) == 255:
                    seed = (x, y)
                    break
            if seed:
                break
        if seed is None:
            return None
        region = mask.copy()
        ImageDraw.floodfill(region, seed, 128)
        box = region.point(lambda value: 255 if value == 128 else 0).getbbox()
        if box is None:
            return None
        width, height = box[2] - box[0], box[3] - box[1]
        if not (120 <= width <= 300 and 100 <= height <= 300):
            return None  # not an eye-sized blank area (e.g. a white background leaked in)
        found.append(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2, min(width, height)))
    (lx, ly, ls), (rx, ry, rs) = found
    return (lx, ly), (rx, ry), max(150, min(230, round(min(ls, rs) * 0.95)))


def save_library_cover(image: Image.Image, left: tuple[int, int], right: tuple[int, int], size: int,
                       folder: Path = LIBRARY_COVERS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    numbers = [int(match.group(1)) for path in folder.glob("cover_*.png") if (match := COVER_FILE_RE.fullmatch(path.stem))]
    number = max(numbers, default=0) + 1
    target = folder / f"cover_{number:03d}__L{left[0]}x{left[1]}_R{right[0]}x{right[1]}_S{size}.png"
    image.convert("RGBA").resize((COVER_CANVAS_SIZE, COVER_CANVAS_SIZE), Image.Resampling.LANCZOS).save(target)
    return target


def load_cover_templates() -> OrderedDict[str, dict[str, object]]:
    templates: OrderedDict[str, dict[str, object]] = OrderedDict()
    try:
        data = json.loads(COVER_TEMPLATES_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return templates
    if not isinstance(data, list):
        return templates
    for item in data:
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("id") or "").strip()
        filename = str(item.get("file") or "").strip()
        if not template_id or not filename:
            continue
        base_filename = str(item.get("base_file") or filename).strip()
        path = COVER_TEMPLATES_DIR / base_filename
        if not path.is_file():
            continue
        title = str(item.get("title") or f"Template {template_id}").strip()
        left_center = item.get("left_center") or [300, 494]
        right_center = item.get("right_center") or [748, 494]
        templates[template_id] = {
            "id": template_id,
            "title": title,
            "label": f"{template_id} • {title}",
            "path": path,
            "sclera_blank": bool(item.get("sclera_blank") or item.get("base_file")),
            "left_center": tuple(int(value) for value in left_center[:2]),
            "right_center": tuple(int(value) for value in right_center[:2]),
            "eye_size": int(item.get("eye_size") or COVER_EYE_SIZE),
        }
    templates.update(load_library_covers())
    return templates


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


def extract_update_archive(archive_path: Path, work_dir: Path) -> Path:
    """Safely unpack the GitHub source archive and return its repository root."""
    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            parts = Path(normalized).parts
            if not parts or normalized.startswith("/") or any(part in ("", ".", "..") for part in parts):
                raise ValueError("ไฟล์อัปเดตมีเส้นทางที่ไม่ปลอดภัย")
            if len(parts) < 2:
                continue
            target = source_dir.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(source_dir.resolve()):
                raise ValueError("ไฟล์อัปเดตอยู่นอกโฟลเดอร์โปรแกรม")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    if not (source_dir / "app" / "blythe_a4_maker.pyw").is_file() and not (
        source_dir / "blythe_a4_maker.pyw"
    ).is_file():
        raise ValueError("ไฟล์ที่ดาวน์โหลดไม่ใช่ Blythe Eye Maker เวอร์ชันที่ถูกต้อง")
    return source_dir


def download_update_archive(work_dir: Path) -> Path:
    archive_path = work_dir / "latest.zip"
    headers = {
        "User-Agent": "Blythe-Eye-Maker-Updater",
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
    }
    commit_url = f"{APP_UPDATE_API_URL}?_={int(datetime.now().timestamp() * 1_000_000)}"
    commit_request = urllib.request.Request(commit_url, headers=headers)
    with urllib.request.urlopen(commit_request, timeout=30) as response:
        commit_sha = json.load(response).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError("GitHub ไม่ได้ส่งหมายเลขเวอร์ชันที่ถูกต้อง")
    archive_url = f"https://github.com/apinanautan/blythe-a4-maker/archive/{commit_sha}.zip"
    request = urllib.request.Request(archive_url, headers={"User-Agent": "Blythe-Eye-Maker-Updater"})
    with urllib.request.urlopen(request, timeout=90) as response, archive_path.open("wb") as archive:
        length = int(response.headers.get("Content-Length", "0") or 0)
        if length > 250 * 1024 * 1024:
            raise ValueError("ไฟล์อัปเดตมีขนาดใหญ่เกินไป")
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 250 * 1024 * 1024:
                raise ValueError("ไฟล์อัปเดตมีขนาดใหญ่เกินไป")
            archive.write(chunk)
    return archive_path


def github_release_info(version: str | None = None) -> dict:
    endpoint = f"{APP_RELEASES_API_URL}/tags/v{version}" if version else f"{APP_RELEASES_API_URL}/latest"
    request_url = f"{endpoint}?_={int(datetime.now().timestamp() * 1_000_000)}"
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "Blythe-Eye-Maker", "Accept": "application/vnd.github+json", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if not isinstance(release, dict) or not release.get("tag_name") or not isinstance(release.get("assets"), list):
        raise ValueError("GitHub ไม่ได้ส่งข้อมูลรีลีสที่ถูกต้อง")
    return release


def version_tuple(version: str) -> tuple[int, ...]:
    """Turn "v1.2.3" into (1, 2, 3) so versions compare numerically."""
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3]) or (0,)


def relaunch_environment() -> dict[str, str]:
    """Environment for starting a fresh copy of the app after an update.

    A PyInstaller one-file EXE sets _PYI_* and Tcl/Tk variables that point at its
    own temporary folder. If the relaunched EXE inherits them it treats itself as
    a child of the old process, looks for that deleted folder and exits silently.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("_PYI_") and key not in {"_MEIPASS2", "TCL_LIBRARY", "TK_LIBRARY"}
    }
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def download_release_asset(release: dict, asset_name: str, destination: Path) -> Path:
    asset = next((item for item in release["assets"] if item.get("name") == asset_name), None)
    if not asset:
        raise ValueError(f"ไม่พบไฟล์ {asset_name} ใน GitHub Release")
    expected_size = int(asset.get("size") or 0)
    if expected_size > 500 * 1024 * 1024:
        raise ValueError("ไฟล์จาก GitHub มีขนาดใหญ่เกินไป")
    request = urllib.request.Request(
        asset["browser_download_url"],
        headers={"User-Agent": "Blythe-Eye-Maker", "Accept": "application/octet-stream"},
    )
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 500 * 1024 * 1024:
                raise ValueError("ไฟล์จาก GitHub มีขนาดใหญ่เกินไป")
            digest.update(chunk)
            output.write(chunk)
    if expected_size and total != expected_size:
        raise ValueError("ขนาดไฟล์ที่ดาวน์โหลดไม่ตรงกับ GitHub")
    expected_digest = str(asset.get("digest") or "")
    if expected_digest.startswith("sha256:") and digest.hexdigest() != expected_digest.removeprefix("sha256:"):
        raise ValueError("ตรวจสอบความถูกต้องของไฟล์จาก GitHub ไม่ผ่าน")
    return destination


def extract_cover_asset_archive(archive_path: Path, destination: Path) -> None:
    """Extract only the published cover-assets folder, rejecting unsafe ZIP paths."""
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            parts = normalized.split("/")
            if (
                normalized.startswith("/")
                or any(part in ("", ".", "..") for part in parts if part)
                or not parts
                or parts[0] != "cover_assets"
            ):
                raise ValueError("ไฟล์ข้อมูลมีเส้นทางที่ไม่ปลอดภัย")
            target = destination.joinpath(*[part for part in parts if part])
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("ไฟล์ข้อมูลอยู่นอกโฟลเดอร์โปรแกรม")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    required = (
        destination / "cover_assets" / "doll_cover_base.png",
        destination / "cover_assets" / "doll_cover_overlay.png",
        destination / "cover_assets" / "templates_gpt_blank" / "manifest.json",
    )
    if not all(path.is_file() for path in required):
        raise ValueError("แพ็กเกจข้อมูลหน้าปกไม่ครบ")


def install_release_assets(archive_path: Path, version: str) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    stage = SETTINGS_DIR / f".release_assets_stage_{os.getpid()}"
    backup = SETTINGS_DIR / f".release_assets_backup_{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    try:
        extract_cover_asset_archive(archive_path, stage)
        (stage / "version.txt").write_text(version, encoding="utf-8")
        if APP_RELEASE_ASSETS_DIR.exists():
            APP_RELEASE_ASSETS_DIR.replace(backup)
        stage.replace(APP_RELEASE_ASSETS_DIR)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if backup.exists() and not APP_RELEASE_ASSETS_DIR.exists():
            backup.replace(APP_RELEASE_ASSETS_DIR)
        shutil.rmtree(stage, ignore_errors=True)
        raise


EXE_UPDATER_SCRIPT = r"""
param([int]$ProcessId, [string]$UpdatedExe, [string]$InstallExe, [string]$WorkDir, [string]$LogFile)
function Log([string]$message) {
  try { Add-Content -LiteralPath $LogFile -Value ("{0:s} {1}" -f (Get-Date), $message) -Encoding UTF8 } catch {}
}
$old = "$InstallExe.old"
try {
  Log "update start pid=$ProcessId new=$UpdatedExe target=$InstallExe"
  Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction SilentlyContinue
  Log "old process closed"
  $deadline = (Get-Date).AddSeconds(60)
  while ($true) {
    try {
      if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
      # Windows lets a running or locked EXE be renamed, so move it aside instead of overwriting it.
      if (Test-Path -LiteralPath $InstallExe) { Move-Item -LiteralPath $InstallExe -Destination $old -Force -ErrorAction Stop }
      Move-Item -LiteralPath $UpdatedExe -Destination $InstallExe -Force -ErrorAction Stop
      break
    } catch {
      Log ("retry: " + $_.Exception.Message)
      if (-not (Test-Path -LiteralPath $InstallExe) -and (Test-Path -LiteralPath $old)) {
        Move-Item -LiteralPath $old -Destination $InstallExe -Force -ErrorAction SilentlyContinue
      }
      if ((Get-Date) -gt $deadline) { throw }
      Start-Sleep -Milliseconds 500
    }
  }
  Log "replaced"
  Start-Process -FilePath $InstallExe -WorkingDirectory (Split-Path -Parent $InstallExe)
  Log "started new version"
  Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
} catch {
  Log ("FAILED: " + $_.Exception.Message)
  # Never leave the user with nothing open: start whichever copy still exists.
  if (Test-Path -LiteralPath $UpdatedExe) { Start-Process -FilePath $UpdatedExe }
  elseif (Test-Path -LiteralPath $InstallExe) { Start-Process -FilePath $InstallExe }
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show(("อัปเดตไม่สำเร็จ: " + $_.Exception.Message + [Environment]::NewLine + "บันทึก: " + $LogFile), "Blythe Eye Maker") | Out-Null
}
"""


# PowerShell started with DETACHED_PROCESS exits at once without running its script
# (verified on Windows in CI); CREATE_NO_WINDOW keeps it hidden and working.
POWERSHELL_HELPER_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def launch_exe_updater(process_id: int, update_file: Path, install_exe: Path, work_dir: Path) -> None:
    """Start the PowerShell helper that swaps in the new EXE after this process exits and reopens it."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    updater = Path(tempfile.gettempdir()) / f"blythe_apply_{process_id}.ps1"
    updater.write_text(EXE_UPDATER_SCRIPT, encoding="utf-8-sig")
    # PowerShell's own errors (e.g. a script that will not start) land here instead of vanishing.
    with UPDATE_LOG_FILE.with_name("update_console.log").open("w", encoding="utf-8") as console:
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater),
                "-ProcessId", str(process_id), "-UpdatedExe", str(update_file), "-InstallExe", str(install_exe),
                "-WorkDir", str(work_dir), "-LogFile", str(UPDATE_LOG_FILE),
            ],
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
            creationflags=POWERSHELL_HELPER_FLAGS,
            close_fds=True,
            env=relaunch_environment(),
        )


def download_latest_release_exe(work_dir: Path) -> Path:
    release = github_release_info()
    return download_release_asset(release, APP_EXECUTABLE_NAME, work_dir / APP_EXECUTABLE_NAME)


def apply_app_icon(window: tk.Misc) -> None:
    """Give the window and taskbar the full-size icon instead of a stretched small one."""
    icon_path = app_resource_path("branding", "BlytheEyeMaker.ico")
    if not icon_path.is_file():
        return
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BlytheEyeMaker")
        except (AttributeError, OSError):
            pass
    try:
        window.iconbitmap(default=str(icon_path))
    except tk.TclError:
        pass
    try:
        with Image.open(icon_path) as icon:
            photos = []
            for size in (256, 128, 64, 48, 32, 16):
                icon.size = (size, size)
                photos.append(ImageTk.PhotoImage(icon.convert("RGBA"), master=window))
        window.iconphoto(True, *photos)
        window._app_icon_photos = photos  # keep references so Tk does not drop them
    except (OSError, ValueError, tk.TclError):
        pass
    if sys.platform == "win32":
        _set_native_window_icons(window, icon_path)


def _set_native_window_icons(window: tk.Misc, icon_path: Path) -> None:
    """Hand Windows the ICO entries at the exact sizes it draws, so the taskbar
    and title bar never show a stretched Tk-generated icon."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        image_icon, load_from_file, wm_seticon = 1, 0x10, 0x80
        for which, metric in ((0, 49), (1, 11)):  # ICON_SMALL/SM_CXSMICON, ICON_BIG/SM_CXICON
            size = user32.GetSystemMetrics(metric)
            handle = user32.LoadImageW(None, str(icon_path), image_icon, size, size, load_from_file)
            if handle:
                user32.SendMessageW(hwnd, wm_seticon, which, handle)
    except (AttributeError, OSError, ValueError, tk.TclError):
        pass


def ensure_release_assets() -> bool:
    """Download the matching cover assets on first run of a standalone EXE."""
    if not getattr(sys, "frozen", False):
        return True
    version_file = APP_RELEASE_ASSETS_DIR / "version.txt"
    required = (COVER_BASE_PATH, COVER_OVERLAY_PATH, COVER_TEMPLATES_MANIFEST)
    try:
        if version_file.read_text(encoding="utf-8").strip() == f"v{APP_VERSION}" and all(
            path.is_file() for path in required
        ):
            return True
    except OSError:
        pass

    root = tk.Tk()
    root.title("Blythe Eye Maker")
    root.geometry("430x185")
    root.resizable(False, False)
    root.configure(bg=UI_BG)
    apply_app_icon(root)
    ttk.Label(root, text="Blythe Eye Maker", font=("Segoe UI", 16, "bold")).pack(pady=(24, 8))
    status = tk.StringVar(value="กำลังเตรียมไฟล์ประกอบจาก GitHub…")
    ttk.Label(root, textvariable=status, style="Muted.TLabel").pack(pady=(0, 12))
    progress = ttk.Progressbar(root, mode="indeterminate", length=350)
    progress.pack(pady=(0, 14))
    progress.start(12)
    actions = ttk.Frame(root)
    retry_button = ttk.Button(actions, text="ลองใหม่", command=lambda: start_download())
    close_button = ttk.Button(actions, text="ปิด", command=root.destroy)
    ready = {"ok": False, "busy": False}

    def start_download() -> None:
        if ready["busy"]:
            return
        ready["busy"] = True
        status.set("กำลังดาวน์โหลดไฟล์หน้าปกและตรวจสอบข้อมูล…")
        progress.start(12)
        actions.pack_forget()

        def worker() -> None:
            temp_dir = Path(tempfile.mkdtemp(prefix="blythe_assets_"))
            try:
                release = github_release_info(APP_VERSION)
                archive = download_release_asset(release, APP_ASSET_ARCHIVE_NAME, temp_dir / "assets.zip")
                install_release_assets(archive, str(release["tag_name"]))
                shutil.rmtree(temp_dir, ignore_errors=True)
                try:
                    root.after(0, lambda: finish(None))
                except tk.TclError:
                    pass
            except Exception as exc:
                shutil.rmtree(temp_dir, ignore_errors=True)
                try:
                    root.after(0, lambda error=str(exc): finish(error))
                except tk.TclError:
                    pass

        threading.Thread(target=worker, name="blythe-first-run-assets", daemon=True).start()

    def finish(error: str | None) -> None:
        ready["busy"] = False
        progress.stop()
        if error:
            status.set("ดาวน์โหลดไม่สำเร็จ ตรวจอินเทอร์เน็ตแล้วลองใหม่")
            actions.pack(pady=(4, 10))
            retry_button.pack(side="left", padx=5)
            close_button.pack(side="left", padx=5)
            root.update_idletasks()
            root.geometry(f"430x210+{root.winfo_screenwidth()//2-215}+{root.winfo_screenheight()//2-105}")
            return
        ready["ok"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    start_download()
    root.update_idletasks()
    root.geometry(f"430x185+{root.winfo_screenwidth()//2-215}+{root.winfo_screenheight()//2-92}")
    root.mainloop()
    return ready["ok"]


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


def discover_custom_a4_items(folder: Path) -> OrderedDict[str, tuple[Path, tuple[Path, ...]]]:
    """Load saved custom eye pairs from the A4 custom library."""
    pairs: dict[int, dict[int, Path]] = {}
    if folder.is_dir():
        for path in folder.glob("custom_*_*.png"):
            match = re.fullmatch(r"custom_(\d+)_(1|2)", path.stem)
            if match:
                pairs.setdefault(int(match.group(1)), {})[int(match.group(2))] = path
    return OrderedDict(
        (f"custom:{number:03d}", (files[1], (files[1], files[2])))
        for number, files in sorted(pairs.items())
        if 1 in files and 2 in files
    )


def next_design_number(folder: Path) -> int:
    """The first free whole number in a set folder, so a deleted number gets reused first."""
    used = {int(key.split(".")[0]) for key in discover_assets(folder)}
    number = 1
    while number in used:
        number += 1
    return number


def create_order(customer: str, root: Path = ORDERS_DIR, now: datetime | None = None) -> Path:
    """Make a folder for one customer's order, e.g. 2026-10-05_Nina."""
    now = now or datetime.now()
    base = f"{now:%Y-%m-%d}_{sanitize_filename(customer) or 'ลูกค้า'}"
    folder = root / base
    number = 2
    while folder.exists():
        folder = root / f"{base}_{number}"
        number += 1
    folder.mkdir(parents=True)
    save_order(folder, {"customer": customer.strip(), "created": now.isoformat(timespec="seconds"),
                        "a4": [], "sheets_4x6": [], "note": ""})
    return folder


def load_order(folder: Path) -> dict:
    try:
        data = json.loads((folder / "order.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_order(folder: Path, data: dict) -> None:
    temporary = folder / "order.json.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(folder / "order.json")


def list_orders(root: Path = ORDERS_DIR) -> list[Path]:
    """Order folders, newest first."""
    if not root.is_dir():
        return []
    return sorted((path for path in root.iterdir() if (path / "order.json").is_file()),
                  key=lambda path: load_order(path).get("created", ""), reverse=True)


def compact_design_numbers(folder: Path) -> dict[str, str]:
    """Renumber a set to 1..N without gaps, keeping order; 52.1/52.2 move together. Returns old->new stems."""
    stems = sorted({path.stem for path in folder.iterdir() if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS and NUMBER_RE.fullmatch(path.stem)}, key=natural_number_key)
    bases = sorted({int(stem.split(".")[0]) for stem in stems})
    new_base = {base: index for index, base in enumerate(bases, start=1)}
    mapping = {}
    for stem in stems:
        base, dot, piece = stem.partition(".")
        new_stem = f"{new_base[int(base)]}{dot}{piece}"
        if new_stem != stem:
            mapping[stem] = new_stem
    staged = []
    for stem in mapping:
        for path in design_files(folder, stem):
            temporary = path.with_name(f".compact_{path.name}")
            path.replace(temporary)
            staged.append((temporary, folder / f"{mapping[stem]}{path.suffix}"))
    for temporary, final in staged:
        temporary.replace(final)
    return mapping


def copy_into_library(old_folders: list[tuple[Path, Path]]) -> int:
    """First run after the library moved inside the program: copy designs from the old folders."""
    copied = 0
    for old, new in old_folders:
        if not old.is_dir() or old.resolve() == new.resolve():
            continue
        new.mkdir(parents=True, exist_ok=True)
        for path in old.iterdir():
            if path.is_file() and path.suffix.lower() in data_sync.SYNC_EXTENSIONS and not (new / path.name).exists():
                shutil.copy2(path, new / path.name)
                copied += 1
    return copied


def design_files(folder: Path, stem: str) -> list[Path]:
    """Every file of one design number (the same design may exist as .psd and .png)."""
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.stem == stem and path.suffix.lower() in VALID_EXTENSIONS
    )


def move_design_to_trash(folder: Path, stem: str, trash_dir: Path = TRASH_DIR) -> str:
    """Move one design's files into the trash so a wrong delete can be undone."""
    files = design_files(folder, stem)
    if not files:
        raise FileNotFoundError(f"ไม่พบไฟล์เบอร์ {stem}")
    entry_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    entry = trash_dir / entry_id
    entry.mkdir(parents=True)
    (entry / "meta.json").write_text(
        json.dumps({"folder": str(folder), "stem": stem, "deleted_at": datetime.now().isoformat(timespec="seconds")},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    for path in files:
        shutil.move(str(path), str(entry / path.name))
    return entry_id


def list_trash(trash_dir: Path = TRASH_DIR) -> list[dict]:
    entries = []
    if trash_dir.is_dir():
        for entry in sorted(trash_dir.iterdir(), reverse=True):
            try:
                meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            meta["id"] = entry.name
            entries.append(meta)
    return entries


def restore_from_trash(entry_id: str, trash_dir: Path = TRASH_DIR) -> str:
    """Put a trashed design back. If its number was reused meanwhile, it gets the first free number."""
    entry = trash_dir / entry_id
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    folder = Path(meta["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    stem = meta["stem"] if not design_files(folder, meta["stem"]) else str(next_design_number(folder))
    for path in entry.iterdir():
        if path.name != "meta.json":
            shutil.move(str(path), str(folder / f"{stem}{path.suffix}"))
    shutil.rmtree(entry, ignore_errors=True)
    return stem


def purge_old_trash(days: int = TRASH_KEEP_DAYS, trash_dir: Path = TRASH_DIR, now: datetime | None = None) -> int:
    """Delete trashed designs older than `days` for good. Returns how many were removed."""
    now = now or datetime.now()
    removed = 0
    for item in list_trash(trash_dir):
        try:
            deleted_at = datetime.fromisoformat(item.get("deleted_at", ""))
        except ValueError:
            continue
        if (now - deleted_at).days >= days:
            purge_trash(item["id"], trash_dir)
            removed += 1
    return removed


def purge_trash(entry_id: str | None = None, trash_dir: Path = TRASH_DIR) -> None:
    """Delete one trashed design, or the whole trash, for good."""
    target = trash_dir / entry_id if entry_id else trash_dir
    shutil.rmtree(target, ignore_errors=True)


def renumber_design(folder: Path, old_stem: str, new_stem: str, swap: bool = False) -> None:
    """Give a design a new number. With swap, the design already at that number takes the old one."""
    if not NUMBER_RE.fullmatch(new_stem):
        raise ValueError("เบอร์ต้องเป็นตัวเลข เช่น 65 หรือ 7.1")
    moving = design_files(folder, old_stem)
    occupied = design_files(folder, new_stem)
    if occupied and not swap:
        raise FileExistsError(f"มีเบอร์ {new_stem} อยู่แล้ว")
    staged = []
    for path in moving:
        temporary = path.with_name(f".renumber_{path.name}")
        path.replace(temporary)
        staged.append((temporary, folder / f"{new_stem}{path.suffix}"))
    for path in occupied:
        path.replace(folder / f"{old_stem}{path.suffix}")
    for temporary, final in staged:
        temporary.replace(final)


def save_image_into_set(image: Image.Image, folder: Path) -> str:
    """Save an eye image (a pair or a single eye) as the next number in a set folder."""
    folder.mkdir(parents=True, exist_ok=True)
    number = next_design_number(folder)
    target = folder / f"{number}.png"
    temporary = folder / f".{number}.tmp.png"
    flatten_to_white(image.convert("RGBA")).save(temporary, format="PNG", dpi=(DPI, DPI))
    temporary.replace(target)
    return str(number)


def save_pair_into_set(pair: tuple[Image.Image, Image.Image], folder: Path) -> str:
    """Save a custom pair as the next numbered two-up file in a set folder (e.g. 64.png)."""
    folder.mkdir(parents=True, exist_ok=True)
    number = next_design_number(folder)
    left, right = (flatten_to_white(eye) for eye in pair)
    sheet = Image.new("RGB", (left.width + right.width, max(left.height, right.height)), "white")
    sheet.paste(left, (0, 0))
    sheet.paste(right, (left.width, 0))
    target = folder / f"{number}.png"
    temporary = folder / f".{number}.tmp.png"
    sheet.save(temporary, format="PNG", dpi=(DPI, DPI))
    temporary.replace(target)
    return str(number)


def migrate_custom_library(folder: Path) -> list[str]:
    """Move pairs saved by older versions in _custom_a4 into the set as next numbers."""
    library = folder / CUSTOM_A4_DIR_NAME
    moved: list[str] = []
    for _custom_id, (_source, (first, second)) in discover_custom_a4_items(library).items():
        with Image.open(first) as left, Image.open(second) as right:
            moved.append(save_pair_into_set((left.convert("RGBA"), right.convert("RGBA")), folder))
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
    return moved


def delete_and_renumber_custom_a4(
    items: OrderedDict[str, tuple[Path, tuple[Path, ...]]],
    remove_id: str,
) -> tuple[OrderedDict[str, tuple[Path, tuple[Path, ...]]], dict[str, str]]:
    """Delete one custom pair's files and renumber the rest 1..N without gaps.

    Returns the renumbered items and a map from old ids to new ids.
    """
    def number(key: str) -> int:
        return int(key.split(":", 1)[1])

    for path in items[remove_id][1]:
        path.unlink(missing_ok=True)
    remaining = sorted((key for key in items if key != remove_id), key=number)

    renamed: OrderedDict[str, tuple[Path, tuple[Path, ...]]] = OrderedDict()
    id_map: dict[str, str] = {}
    staged: list[tuple[Path, Path]] = []
    for new_number, old_id in enumerate(remaining, start=1):
        new_id = f"custom:{new_number:03d}"
        source, paths = items[old_id]
        new_paths = tuple(
            path.with_name(f"custom_{new_number:03d}_{index}.png") for index, path in enumerate(paths, start=1)
        )
        if new_paths != paths:
            for path, new_path in zip(paths, new_paths):
                # Rename through a temporary name so 2 -> 1 never overwrites a file still waiting to move.
                temporary = path.with_name(f".renumber_{new_number:03d}_{new_path.name}")
                path.replace(temporary)
                staged.append((temporary, new_path))
            if source in paths:
                source = new_paths[paths.index(source)]
        renamed[new_id] = (source, new_paths)
        id_map[old_id] = new_id
    for temporary, final in staged:
        temporary.replace(final)
    return renamed, id_map


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


def remove_outer_background(image: Image.Image, threshold: int = 42) -> Image.Image:
    """Remove the sampled edge color while preserving enclosed pixels of that color."""
    rgba = image.convert("RGBA")
    rgb = rgba.convert("RGB")
    width, height = rgb.size
    corners = (rgb.getpixel((0, 0)), rgb.getpixel((width - 1, 0)), rgb.getpixel((0, height - 1)), rgb.getpixel((width - 1, height - 1)))
    background = tuple(sorted(pixel[channel] for pixel in corners)[len(corners) // 2] for channel in range(3))
    candidates = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    candidates = candidates.convert("L").point(lambda value: 255 if value <= threshold else 0)
    width, height = candidates.size
    for x in range(width):
        if candidates.getpixel((x, 0)):
            ImageDraw.floodfill(candidates, (x, 0), 128)
        if candidates.getpixel((x, height - 1)):
            ImageDraw.floodfill(candidates, (x, height - 1), 128)
    for y in range(height):
        if candidates.getpixel((0, y)):
            ImageDraw.floodfill(candidates, (0, y), 128)
        if candidates.getpixel((width - 1, y)):
            ImageDraw.floodfill(candidates, (width - 1, y), 128)
    foreground = candidates.point(lambda value: 0 if value == 128 else 255)
    rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), foreground))
    return rgba


def _has_white_background(image: Image.Image) -> bool:
    rgb = image.convert("RGB")
    corners = (
        rgb.getpixel((0, 0)),
        rgb.getpixel((rgb.width - 1, 0)),
        rgb.getpixel((0, rgb.height - 1)),
        rgb.getpixel((rgb.width - 1, rgb.height - 1)),
    )
    return all(min(pixel) >= 220 and max(pixel) - min(pixel) <= 45 for pixel in corners)


def _has_uniform_edge_background(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    points = ((0, 0), (rgba.width - 1, 0), (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1))
    corners = [rgba.getpixel(point) for point in points]
    if min(pixel[3] for pixel in corners) < 240:
        return False
    spread = max(max(pixel[channel] for pixel in corners) - min(pixel[channel] for pixel in corners) for channel in range(3))
    background = tuple(sorted(pixel[channel] for pixel in corners)[len(corners) // 2] for channel in range(3))
    center = rgba.getpixel((rgba.width // 2, rgba.height // 2))
    center_difference = sum(abs(center[channel] - background[channel]) for channel in range(3)) / 3
    return spread <= 32 and center_difference >= 30


def background_kind(image: Image.Image) -> str:
    """'transparent' (real alpha), 'checker' (a fake transparency pattern baked into the pixels) or 'solid'."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    edge = max(4, min(width, height) // 12)
    corners = [rgba.crop(box) for box in (
        (0, 0, edge, edge), (width - edge, 0, width, edge),
        (0, height - edge, edge, height), (width - edge, height - edge, width, height),
    )]
    if all(corner.getchannel("A").getextrema()[1] < 128 for corner in corners):
        return "transparent"
    checker_corners = 0
    for corner in corners:
        gray = corner.convert("L")
        low, high = gray.getextrema()
        saturation = corner.convert("HSV").getchannel("S").getextrema()[1]
        if high >= 230 and 150 <= low <= 225 and high - low >= 12 and saturation <= 30:
            checker_corners += 1
    return "checker" if checker_corners >= 3 else "solid"


def remove_checker_background(image: Image.Image) -> Image.Image:
    """Make a baked-in light grey/white checkerboard around the eye truly transparent."""
    rgba = image.convert("RGBA")
    hsv = rgba.convert("HSV")
    light = rgba.convert("L").point(lambda value: 255 if value >= 150 else 0)
    pale = hsv.getchannel("S").point(lambda value: 255 if value <= 30 else 0)
    mask = ImageChops.multiply(light, pale)
    width, height = mask.size
    # Only checker pixels connected to the border are background; pale pixels inside the eye stay.
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if mask.getpixel((x, y)) == 255:
            ImageDraw.floodfill(mask, (x, y), 128)
    background = mask.point(lambda value: 255 if value == 128 else 0)
    alpha = ImageChops.subtract(rgba.getchannel("A"), background)
    rgba.putalpha(alpha)
    return rgba


def trim_custom_a4_transparent_margin(image: Image.Image, threshold: int = 12) -> Image.Image:
    """Center crop artwork by its visible pixels instead of uneven empty file margins."""
    rgba = image.convert("RGBA")
    visible = rgba.getchannel("A").point(lambda alpha: 255 if alpha > threshold else 0)
    bounds = visible.getbbox()
    return rgba.crop(bounds) if bounds else rgba


def make_custom_a4_pair(
    image: Image.Image,
    size_px: int,
    zoom: float = 1.0,
    remove_background: bool = False,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
) -> tuple[Image.Image, Image.Image]:
    """Fit custom art to equal circular print slots, optionally removing edge-connected white."""
    source = image.convert("RGBA")
    if source.width >= source.height * 1.7:
        midpoint = source.width // 2
        pieces = (source.crop((0, 0, midpoint, source.height)), source.crop((midpoint, 0, source.width, source.height)))
    else:
        pieces = (source, source.copy())

    zoom = max(0.25, min(float(zoom), 2.5))
    outputs: list[Image.Image] = []
    for piece in pieces:
        if remove_background:
            piece = remove_outer_background(piece)
        scale = size_px * zoom / max(piece.size)
        resized = piece.resize(
            (max(1, round(piece.width * scale)), max(1, round(piece.height * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        pan_x = max(-1.0, min(float(pan_x), 1.0))
        pan_y = max(-1.0, min(float(pan_y), 1.0))
        dest_x = (
            -round((resized.width - size_px) * (1 - pan_x) / 2)
            if resized.width > size_px
            else round((size_px - resized.width) * (1 + pan_x) / 2)
        )
        dest_y = (
            -round((resized.height - size_px) * (1 - pan_y) / 2)
            if resized.height > size_px
            else round((size_px - resized.height) * (1 + pan_y) / 2)
        )
        source_box = (
            max(0, -dest_x),
            max(0, -dest_y),
            min(resized.width, size_px - dest_x),
            min(resized.height, size_px - dest_y),
        )
        if source_box[2] > source_box[0] and source_box[3] > source_box[1]:
            canvas.alpha_composite(resized.crop(source_box), (max(0, dest_x), max(0, dest_y)))
        mask = Image.new("L", (size_px * 4, size_px * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size_px * 4 - 1, size_px * 4 - 1), fill=255)
        canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), mask.resize((size_px, size_px), Image.Resampling.LANCZOS)))
        outputs.append(canvas)
    return outputs[0], outputs[1]


def make_custom_a4_crop_preview(
    image: Image.Image,
    size_px: int,
    zoom: float,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
) -> Image.Image:
    """Render the small interactive crop preview without the print-resolution pipeline."""
    source = image.convert("RGBA")
    if source.width >= source.height * 1.7:
        source = source.crop((0, 0, source.width // 2, source.height))
    scale = max(0.25, min(float(zoom), 2.5)) * size_px / max(source.size)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.BILINEAR,
    )
    dest_x = (
        -round((resized.width - size_px) * (1 - pan_x) / 2)
        if resized.width > size_px
        else round((size_px - resized.width) * (1 + pan_x) / 2)
    )
    dest_y = (
        -round((resized.height - size_px) * (1 - pan_y) / 2)
        if resized.height > size_px
        else round((size_px - resized.height) * (1 + pan_y) / 2)
    )
    source_box = (
        max(0, -dest_x),
        max(0, -dest_y),
        min(resized.width, size_px - dest_x),
        min(resized.height, size_px - dest_y),
    )
    preview = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    if source_box[2] > source_box[0] and source_box[3] > source_box[1]:
        preview.alpha_composite(resized.crop(source_box), (max(0, dest_x), max(0, dest_y)))
    return preview


def make_custom_a4_crop_guide(size_px: int) -> Image.Image:
    """Draw a fixed, centered circular crop guide over the movable source image."""
    scale = 4
    size = max(1, int(size_px))
    hi_size = size * scale
    # Dim everything that will be cut away so the kept circle stands out.
    guide = Image.new("RGBA", (hi_size, hi_size), (25, 32, 28, 175))
    draw = ImageDraw.Draw(guide)
    bounds = (0, 0, hi_size - 1, hi_size - 1)
    draw.ellipse(bounds, fill=(0, 0, 0, 0))
    # The white line sits exactly on the cut edge; the dark line just inside it
    # keeps the edge readable over both bright and dark artwork.
    draw.ellipse(bounds, outline=(255, 255, 255, 255), width=2 * scale)
    inset = 2 * scale
    draw.ellipse(
        (inset, inset, hi_size - 1 - inset, hi_size - 1 - inset),
        outline=(20, 28, 24, 200),
        width=1 * scale,
    )
    return guide.resize((size, size), Image.Resampling.LANCZOS)


def make_custom_a4_pair_as_is(image: Image.Image, size_px: int) -> tuple[Image.Image, Image.Image]:
    """Place complete artwork in the standard square print size without cropping or masking."""
    source = image.convert("RGBA")
    if source.width >= source.height * 1.7:
        midpoint = source.width // 2
        pieces = (source.crop((0, 0, midpoint, source.height)), source.crop((midpoint, 0, source.width, source.height)))
    else:
        pieces = (source, source.copy())

    result: list[Image.Image] = []
    for piece in pieces:
        if piece.getchannel("A").getextrema()[0] < 250:
            # Real transparency: select the eye itself (like Photoshop's object select) so it fills the size.
            piece = trim_custom_a4_transparent_margin(piece)
        fitted = ImageOps.contain(piece, (size_px, size_px), Image.Resampling.LANCZOS)
        corners = [piece.getpixel(point) for point in ((0, 0), (piece.width - 1, 0), (0, piece.height - 1), (piece.width - 1, piece.height - 1))]
        background = (255, 255, 255, 255) if all(pixel[3] == 255 for pixel in corners) else (0, 0, 0, 0)
        canvas = Image.new("RGBA", (size_px, size_px), background)
        canvas.alpha_composite(fitted, ((size_px - fitted.width) // 2, (size_px - fitted.height) // 2))
        result.append(canvas)
    return result[0], result[1]


def _sample_template_sclera_color(
    canvas: Image.Image,
    center: tuple[int, int],
    clear_size: int,
) -> tuple[int, int, int]:
    """Sample the existing eye white immediately beside an iris."""
    cx, cy = center
    radius = clear_size // 2
    samples: list[tuple[int, int, int]] = []
    for direction in (-1, 1):
        sample_x = cx + direction * (radius + 8)
        for y in range(cy - 10, cy + 11, 2):
            for x in range(sample_x - 5, sample_x + 6, 2):
                if not (0 <= x < canvas.width and 0 <= y < canvas.height):
                    continue
                r, g, b, _a = canvas.getpixel((x, y))
                average = (r + g + b) / 3
                # Keep only bright, low-saturation pixels so hair/skin/liner
                # cannot tint the replacement sclera.
                if average >= 180 and max(r, g, b) - min(r, g, b) <= 55:
                    samples.append((r, g, b))
    if not samples:
        return (250, 248, 247)
    middle = len(samples) // 2
    median = tuple(
        sorted(pixel[channel] for pixel in samples)[middle]
        for channel in range(3)
    )
    # Keep a hint of the template's warm/cool sclera tone, but make the base
    # unmistakably eye-white rather than carrying blush/iris color forward.
    return tuple(round(value * 0.25 + 255 * 0.75) for value in median)


def _blank_template_iris(
    canvas: Image.Image,
    center: tuple[int, int],
    clear_size: int,
) -> None:
    """Replace a baked-in iris with natural sclera before inserting a new eye chip."""
    color = _sample_template_sclera_color(canvas, center, clear_size)
    scale = 4
    mask_large = Image.new("L", (clear_size * scale, clear_size * scale), 0)
    ImageDraw.Draw(mask_large).ellipse(
        (0, 0, clear_size * scale - 1, clear_size * scale - 1),
        fill=255,
    )
    mask = mask_large.resize((clear_size, clear_size), Image.Resampling.LANCZOS)
    patch = Image.new("RGBA", (clear_size, clear_size), (*color, 255))
    patch.putalpha(mask)
    cx, cy = center
    canvas.alpha_composite(
        patch,
        (round(cx - clear_size / 2), round(cy - clear_size / 2)),
    )


def render_doll_cover(
    prepared_assets: OrderedDict[str, tuple[Path, ...]],
    design_id: str,
    template: dict[str, object] | None = None,
    base_path: Path = COVER_BASE_PATH,
    overlay_path: Path = COVER_OVERLAY_PATH,
) -> Image.Image:
    """Render one customer cover using the selected doll template and eye design."""
    if template is not None:
        template_path = Path(template["path"])
        with Image.open(template_path) as opened:
            canvas = opened.convert("RGBA").resize(
                (COVER_CANVAS_SIZE, COVER_CANVAS_SIZE), Image.Resampling.LANCZOS
            )
        eye_size = int(template.get("eye_size") or COVER_EYE_SIZE)
        chips = cached_design_chips(prepared_assets, design_id, eye_size)
        left = make_round_ui_thumbnail(chips[0], eye_size)
        right_source = chips[1] if len(chips) > 1 else chips[0]
        right = make_round_ui_thumbnail(right_source, eye_size)
        left_center = tuple(template.get("left_center") or (300, 494))
        right_center = tuple(template.get("right_center") or (748, 494))
        if not template.get("sclera_blank"):
            clear_size = int(template.get("sclera_clear_size") or COVER_TEMPLATE_SCLERA_SIZE)
            clear_size = max(clear_size, eye_size + 20)
            # Backward-compatible fallback for old flattened templates.
            _blank_template_iris(canvas, left_center, clear_size)
            _blank_template_iris(canvas, right_center, clear_size)
        radius = eye_size / 2
        left_pos = (round(left_center[0] - radius), round(left_center[1] - radius))
        right_pos = (round(right_center[0] - radius), round(right_center[1] - radius))
        canvas.alpha_composite(left, left_pos)
        canvas.alpha_composite(right, right_pos)
        return canvas

    if not base_path.exists() or not overlay_path.exists():
        raise FileNotFoundError("ไม่พบไฟล์ต้นแบบรูปปก")

    with Image.open(base_path) as opened:
        canvas = opened.convert("RGBA")
    with Image.open(overlay_path) as opened:
        overlay = opened.convert("RGBA")

    if canvas.size != (COVER_CANVAS_SIZE, COVER_CANVAS_SIZE) or overlay.size != canvas.size:
        raise ValueError("ไฟล์ต้นแบบรูปปกต้องมีขนาด 1000×1000 px")

    chips = cached_design_chips(prepared_assets, design_id, COVER_EYE_SIZE)
    left = make_round_ui_thumbnail(chips[0], COVER_EYE_SIZE)
    right_source = chips[1] if len(chips) > 1 else chips[0]
    right = make_round_ui_thumbnail(right_source, COVER_EYE_SIZE)
    canvas.alpha_composite(left, COVER_LEFT_EYE_POS)
    canvas.alpha_composite(right, COVER_RIGHT_EYE_POS)
    canvas.alpha_composite(overlay)
    return canvas


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
            chip = flatten_to_white(opened)
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
        if pair_index == 0:
            # A design from Data, a crop or the AI page rather than a pair on a 4x6 sheet.
            left, right = (make_chip(piece, size_px) for piece in split_or_duplicate_pair(path))
        else:
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


class BlytheA4App(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Blythe Eye Maker v{APP_VERSION}")
        apply_app_icon(self)
        self.geometry("760x560")
        self.minsize(680, 500)
        self.configure(bg=UI_BG)
        self._configure_theme()

        saved_settings = load_user_settings()
        saved_source = saved_settings.get("source_folder", "").strip()
        saved_source_4x6 = saved_settings.get("source_4x6_folder", "").strip()
        for folder in (LIBRARY_SET1, LIBRARY_SET2, LIBRARY_4X6):
            folder.mkdir(parents=True, exist_ok=True)
        if saved_settings.get("library_migrated") != "1":
            # Bring designs over from the folders older versions used (e.g. Dropbox); they stay where they were.
            old_set1 = Path(saved_source) if saved_source else None
            old_pairs = []
            if old_set1 is not None:
                old_set2 = Path(saved_settings.get("set2_folder") or second_source_folder(old_set1))
                old_4x6 = Path(saved_source_4x6) if saved_source_4x6 else old_set1.parent / "ไฟล์ตา"
                old_pairs = [(old_set1, LIBRARY_SET1), (old_set2, LIBRARY_SET2), (old_4x6, LIBRARY_4X6)]
            try:
                copy_into_library(old_pairs)
                saved_settings["library_migrated"] = "1"
                save_user_settings(saved_settings)
            except OSError:
                pass

        self.source_var = tk.StringVar(value=str(LIBRARY_SET1))
        self.source_4x6_var = tk.StringVar(value=str(LIBRARY_4X6))
        self.output_var = tk.StringVar(value=str(DEFAULT_DATA_ROOT / "A4_ลูกค้า"))
        self.output_4x6_var = tk.StringVar(value=str(DEFAULT_DATA_ROOT / "4x6_ลูกค้า"))
        self.customer_var = tk.StringVar()
        self.sync_status_var = tk.StringVar(value="ยังไม่ได้ซิงค์")
        self._data_sync_running = False
        self._data_sync_again = False
        self.cache_var = tk.StringVar(value="กำลังตรวจไฟล์...")
        self.six_status_var = tk.StringVar(value="0 / 16 คู่")
        self.six_sheet_var = tk.StringVar()
        self.ai_single_status_var = tk.StringVar(value="พร้อมสร้าง 1 คู่")
        self.ai_collection_status_var = tk.StringVar(value="พร้อมวางแผน 16 คู่")
        self.ai_style_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_background_var = tk.StringVar(value="โปร่งใส")
        self.ai_design_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_primary_color_var = tk.StringVar(value="อัตโนมัติ")
        self.ai_secondary_color_var = tk.StringVar(value="อัตโนมัติ")
        self.current_page = "a4"

        self.assets: OrderedDict[str, Path] = OrderedDict()
        self.prepared_assets: OrderedDict[str, tuple[Path, ...]] = OrderedDict()
        self.custom_a4_temp = tempfile.TemporaryDirectory(prefix="blythe_a4_custom_")
        self.custom_a4_items: OrderedDict[str, tuple[Path, tuple[Path, ...]]] = OrderedDict()
        self.custom_a4_counter = 0
        self.custom_a4_image: Image.Image | None = None
        self.custom_a4_preview_image: Image.Image | None = None
        self.custom_a4_crop_source: Image.Image | None = None
        self.custom_a4_crop_preview_image: Image.Image | None = None
        self.custom_a4_crop_mode = False
        self.custom_a4_source_path: Path | None = None
        self.custom_a4_zoom = tk.IntVar(value=100)
        self.custom_a4_crop_status = tk.StringVar(value="ลากรูปมาวางในช่อง หรือคลิกเพื่อเลือก")
        self.custom_a4_crop_photo: ImageTk.PhotoImage | None = None
        self.custom_a4_crop_canvas: tk.Canvas | None = None
        self.custom_a4_zoom_scale: tk.Scale | None = None
        self.custom_a4_crop_buttons: list[ttk.Button] = []
        self.custom_a4_pan_x = 0.0
        self.custom_a4_pan_y = 0.0
        self.custom_a4_pan_last: tuple[int, int] | None = None
        self.cache_stats: dict[str, object] = {}
        self.design_ids: list[str] = []
        self.selections: OrderedDict[str, int] = OrderedDict()
        self.selection_history: list[str] = []
        self.number_buttons: dict[str, tk.Button] = {}
        self.thumbnails: dict[str, ImageTk.PhotoImage] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.cover_selected_id: str | None = None
        self.cover_preview_photo: ImageTk.PhotoImage | None = None
        self.cover_templates = load_cover_templates()
        self.cover_random_label = "★ สุ่มปก"
        self.cover_template_labels = OrderedDict(
            [(self.cover_random_label, "__random__")]
            + [
                (str(item["label"]), template_id)
                for template_id, item in self.cover_templates.items()
            ]
        )
        self.cover_random_template_id: str | None = None
        self.cover_template_var = tk.StringVar(value=self.cover_random_label)
        self.six_sheets: OrderedDict[str, Path] = OrderedDict()
        self.six_pair_refs: OrderedDict[str, tuple[Path, int]] = OrderedDict()
        self.six_extra_refs: OrderedDict[str, tuple[Path, int]] = OrderedDict()
        self.six_selections: OrderedDict[str, int] = OrderedDict()
        self.six_selection_history: list[str] = []
        self.six_number_buttons: dict[str, tk.Button] = {}
        self.six_thumbnails: dict[str, ImageTk.PhotoImage] = {}
        self.six_preview_photo: ImageTk.PhotoImage | None = None
        self.ai_image: Image.Image | None = None
        self.ai_image_path: Path | None = None
        self.ai_reference_image: Path | None = None
        self.ai_reference_temp_path: Path | None = None
        self.ai_single_conversation_state: dict[str, str] = {}
        self.ai_single_preview_photo: ImageTk.PhotoImage | None = None
        self.ai_collection_preview_photo: ImageTk.PhotoImage | None = None
        self.ai_collection_plan: dict | None = None
        self.ai_collection_state: dict[str, str] | None = None
        self.ai_collection_prompt = ""
        self.portal_status_var = tk.StringVar(value="ปิดอยู่")
        self.portal_url_var = tk.StringVar(value="ปิดอยู่ — ยังไม่มีลิงก์ใช้งาน")
        self.customer_portal: CustomerPortal | None = None
        self._last_ntfy_customer_url: str | None = None

        self._build_ui()
        self.bind_all("<Control-v>", self._on_ai_reference_paste_shortcut, add="+")
        screenshot_dir = os.environ.get("BLYTHE_UI_SCREENSHOT_DIR")
        if screenshot_dir:
            import time

            self.geometry("980x900+0+0")
            self.after(1000, self._ci_screenshot_tick, Path(screenshot_dir), time.time())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        source_a4_ok = Path(self.source_var.get()).is_dir()
        source_4x6_ok = Path(self.source_4x6_var.get()).is_dir()
        if source_a4_ok and source_4x6_ok:
            if discover_assets(Path(self.source_var.get())):
                self.reload_assets()
            else:
                self.cache_var.set("กำลังโหลดลายตาจาก GitHub…")
            self.after(500, self._start_data_sync)
        else:
            self.cache_var.set("ตั้งค่า Source ครั้งแรก")
            self.after(150, self.open_settings)

    def _ci_screenshot_tick(self, folder: Path, started: float, stage: int = 0) -> None:
        """CI only (BLYTHE_UI_SCREENSHOT_DIR): save screenshots of the main window and settings, then quit."""
        import time

        def grab(window: tk.Misc, name: str) -> None:
            window.update()
            box = (window.winfo_rootx(), window.winfo_rooty(),
                   window.winfo_rootx() + window.winfo_width(), window.winfo_rooty() + window.winfo_height())
            ImageGrab.grab(bbox=box, all_screens=True).save(folder / name)

        if stage == 0:
            if not getattr(self, "_data_sync_finished_once", False) and time.time() - started < 150:
                self.after(1000, self._ci_screenshot_tick, folder, started, 0)
                return
            self._show_page("a4")
            self.after(1500, self._ci_screenshot_tick, folder, started, 1)
        elif stage == 1:
            grab(self, "a4.png")
            self._show_page("crop")
            self.after(1500, self._ci_screenshot_tick, folder, started, 2)
        elif stage == 2:
            grab(self, "crop.png")
            self._show_page("orders")
            self.after(1500, self._ci_screenshot_tick, folder, started, 3)
        elif stage == 3:
            grab(self, "orders.png")
            self._show_page("cover")
            self.after(1500, self._ci_screenshot_tick, folder, started, 5)
        elif stage == 5:
            grab(self, "cover.png")
            self.open_settings()
            self.after(2500, self._ci_screenshot_tick, folder, started, 4)
        else:
            dialogs = [child for child in self.winfo_children() if isinstance(child, tk.Toplevel)]
            if dialogs:
                grab(dialogs[-1], "settings.png")
            (folder / "done.txt").write_text(self.cache_var.get() + "\n" + self.sync_status_var.get(), encoding="utf-8")
            self.destroy()

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
        self.page_host = ttk.Frame(outer)
        self.page_host.pack(fill="both", expand=True)
        page_specs = (
            ("crop", "✂ ขอบลูกตา", self._build_crop_page),
            ("a4", "A4", self._build_a4_page),
            ("4x6", "4×6 นิ้ว", self._build_4x6_page),
            ("ai_single", "AI 1 คู่", self._build_ai_single_page),
            ("ai_collection", "AI 16 คู่", self._build_ai_collection_page),
            ("cover", "รูปปก", self._build_cover_page),
            ("orders", "ลูกค้า", self._build_orders_page),
        )
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        for index, (name, label, _builder) in enumerate(page_specs):
            button = tk.Button(
                nav,
                text=label,
                command=lambda value=name: self._show_page(value),
                relief="flat",
                bd=0,
                padx=14,
                pady=6,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                highlightthickness=0,
            )
            button.pack(side="left", padx=(0 if index == 0 else 4, 0))
            self.nav_buttons[name] = button
            self.pages[name] = ttk.Frame(self.page_host)
        self.a4_page = self.pages["a4"]
        self.six_page = self.pages["4x6"]
        self.ai_single_page = self.pages["ai_single"]
        self.ai_collection_page = self.pages["ai_collection"]
        self.cover_page = self.pages["cover"]
        for name, _label, builder in page_specs:
            builder(self.pages[name])
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self._show_page("a4")

    def _build_orders_page(self, parent: ttk.Frame) -> None:
        self.current_order: Path | None = None
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        tk.Button(
            left,
            text="＋ ออเดอร์ใหม่",
            command=self._new_order,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            pady=6,
            cursor="hand2",
        ).pack(fill="x")
        self.orders_list = tk.Listbox(left, width=30, height=24, activestyle="none", exportselection=False)
        self.orders_list.pack(fill="y", expand=True, pady=(6, 0))
        self.orders_list.bind("<<ListboxSelect>>", lambda _event: self._select_order())
        self._order_folders: list[Path] = []

        right = tk.Frame(body, bg=UI_SURFACE, highlightthickness=1, highlightbackground=UI_BORDER, padx=14, pady=12)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.order_title_var = tk.StringVar(value="เลือกออเดอร์ทางซ้าย หรือกด ออเดอร์ใหม่")
        tk.Label(right, textvariable=self.order_title_var, font=("Segoe UI", 12, "bold"), fg=UI_ACCENT_DARK,
                 bg=UI_SURFACE).pack(anchor="w")
        self.order_detail_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.order_detail_var, font=("Segoe UI", 9), fg=UI_TEXT, bg=UI_SURFACE,
                 justify="left", wraplength=420).pack(anchor="w", pady=(6, 10))

        def step(title: str) -> tk.Frame:
            box = tk.Frame(right, bg=UI_SURFACE)
            box.pack(fill="x", pady=(4, 8))
            tk.Label(box, text=title, font=("Segoe UI", 9, "bold"), fg=UI_TEXT, bg=UI_SURFACE).pack(anchor="w", pady=(0, 4))
            return box

        pick = step("① เลือกลายในหน้า A4 / 4×6 แล้วกด")
        ttk.Button(pick, text="ใส่รายการที่เลือกอยู่ลงออเดอร์นี้", command=self._save_selection_to_order).pack(fill="x")
        ttk.Button(pick, text="โหลดรายการของออเดอร์นี้กลับไปแก้", command=self._load_order_selection).pack(fill="x", pady=(6, 0))
        make = step("② ทำไฟล์พร้อมพิมพ์")
        tk.Button(
            make,
            text="ทำไฟล์พร้อมพิมพ์ลงโฟลเดอร์ออเดอร์",
            command=self._print_order,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            pady=6,
            cursor="hand2",
        ).pack(fill="x")
        other = tk.Frame(right, bg=UI_SURFACE)
        other.pack(fill="x", pady=(8, 0))
        ttk.Button(other, text="เปิดโฟลเดอร์", command=self._open_order_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(other, text="ลบออเดอร์", command=self._delete_order).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _refresh_orders(self, select: Path | None = None) -> None:
        self._order_folders = list_orders()
        self.orders_list.delete(0, "end")
        for folder in self._order_folders:
            data = load_order(folder)
            count = len(data.get("a4", [])) + len(data.get("sheets_4x6", []))
            self.orders_list.insert("end", f"{data.get('created', '')[:10]}  {data.get('customer', folder.name)}  ({count} คู่)")
        target = select or self.current_order
        if target in self._order_folders:
            index = self._order_folders.index(target)
            self.orders_list.selection_clear(0, "end")
            self.orders_list.selection_set(index)
            self.orders_list.see(index)
        self._show_order(target if target in self._order_folders else None)

    def _select_order(self) -> None:
        picked = self.orders_list.curselection()
        if picked:
            self._show_order(self._order_folders[picked[0]])

    def _show_order(self, folder: Path | None) -> None:
        self.current_order = folder
        if folder is None:
            self.order_title_var.set("เลือกออเดอร์ทางซ้าย หรือกด ออเดอร์ใหม่")
            self.order_detail_var.set(f"ออเดอร์เก็บที่ {ORDERS_DIR}")
            return
        data = load_order(folder)
        self.customer_var.set(data.get("customer", ""))
        self.order_title_var.set(f"{data.get('customer', '')} • {data.get('created', '')[:16].replace('T', ' ')}")
        a4_counts: OrderedDict[str, int] = OrderedDict()
        for key in data.get("a4", []):
            a4_counts[key] = a4_counts.get(key, 0) + 1
        a4_text = ", ".join(
            f"{display_design_id(key)}×{count}" if count > 1 else display_design_id(key) for key, count in a4_counts.items()
        ) or "-"
        six_text = f"{len(data.get('sheets_4x6', []))} คู่" if data.get("sheets_4x6") else "-"
        files = sorted(path.name for path in folder.iterdir() if path.suffix.lower() == ".png")
        self.order_detail_var.set(
            f"A4: {a4_text}\n4×6: {six_text}\n\nไฟล์พร้อมพิมพ์: " + (", ".join(files) if files else "ยังไม่ได้ทำ")
        )

    def _new_order(self) -> None:
        name = simpledialog.askstring("ออเดอร์ใหม่", "ชื่อลูกค้า", initialvalue=self.customer_var.get(), parent=self)
        if not name or not name.strip():
            return
        try:
            folder = create_order(name)
        except OSError as exc:
            messagebox.showerror("สร้างออเดอร์ไม่ได้", str(exc), parent=self)
            return
        self._refresh_orders(select=folder)

    def _require_order(self) -> Path | None:
        if self.current_order is None or not self.current_order.is_dir():
            messagebox.showinfo("ยังไม่ได้เลือกออเดอร์", "เลือกออเดอร์ทางซ้าย หรือกด ออเดอร์ใหม่ ก่อน", parent=self)
            return None
        return self.current_order

    def _save_selection_to_order(self) -> None:
        folder = self._require_order()
        if folder is None:
            return
        sheets = [key for key in self.six_selection_history if not key.startswith("data::")]
        skipped = len(self.six_selection_history) - len(sheets)
        if not self.selection_history and not sheets:
            messagebox.showinfo("ยังไม่ได้เลือก", "เลือกลายในหน้า A4 หรือ 4×6 ก่อน", parent=self)
            return
        data = load_order(folder)
        data["a4"] = [key for key in self.selection_history if not key.startswith("custom:")]
        data["sheets_4x6"] = sheets
        save_order(folder, data)
        self._refresh_orders(select=folder)
        if skipped or any(key.startswith("custom:") for key in self.selection_history):
            messagebox.showinfo(
                "บันทึกแล้ว",
                "รูปชั่วคราว (ครอป/AI ที่ยังไม่ได้บันทึกเข้าแบบที่หนึ่ง) เก็บในออเดอร์ไม่ได้\n"
                "กด บันทึกเข้าแบบที่หนึ่ง ก่อน แล้วค่อยใส่ลงออเดอร์",
                parent=self,
            )

    def _load_order_selection(self) -> None:
        folder = self._require_order()
        if folder is None:
            return
        data = load_order(folder)
        self.selections.clear()
        self.selection_history = [key for key in data.get("a4", []) if key in self.assets]
        for key in self.selection_history:
            self.selections[key] = self.selections.get(key, 0) + 1
        self.six_selections.clear()
        self.six_selection_history = [key for key in data.get("sheets_4x6", []) if key in self.six_pair_refs]
        for key in self.six_selection_history:
            self.six_selections[key] = self.six_selections.get(key, 0) + 1
        self.refresh_selection_status()
        self.refresh_4x6_selection_status()
        missing = len(data.get("a4", [])) - len(self.selection_history) + len(data.get("sheets_4x6", [])) - len(self.six_selection_history)
        self._show_page("a4")
        if missing:
            messagebox.showinfo("บางลายหายไป", f"มี {missing} คู่ที่ไม่พบแล้ว (อาจถูกลบหรือเปลี่ยนเบอร์)", parent=self)

    def _print_order(self) -> None:
        folder = self._require_order()
        if folder is None:
            return
        data = load_order(folder)
        a4_keys = [key for key in data.get("a4", []) if key in self.assets]
        six_keys = [key for key in data.get("sheets_4x6", []) if key in self.six_pair_refs]
        if not a4_keys and not six_keys:
            messagebox.showinfo("ออเดอร์ว่าง", "ใส่รายการลงออเดอร์ก่อน", parent=self)
            return
        outputs: list[Path] = []
        try:
            if a4_keys:
                counts: OrderedDict[str, int] = OrderedDict()
                for key in a4_keys:
                    counts[key] = counts.get(key, 0) + 1
                outputs += build_a4_pages(
                    self.assets, counts, folder, customer_name=data.get("customer", ""),
                    diameter_mm=DEFAULT_DIAMETER_MM, prepared_assets=self.prepared_assets,
                )
            if six_keys:
                outputs += build_4x6_pages(self.six_pair_refs, six_keys, folder, customer_name=data.get("customer", ""))
        except Exception as exc:
            messagebox.showerror("ทำไฟล์ไม่สำเร็จ", str(exc), parent=self)
            return
        self._show_order(folder)
        messagebox.showinfo("ทำไฟล์แล้ว", f"ได้ {len(outputs)} ไฟล์ในโฟลเดอร์ออเดอร์", parent=self)

    def _open_order_folder(self) -> None:
        folder = self._require_order()
        if folder is not None:
            subprocess.Popen(["explorer", str(folder)])

    def _delete_order(self) -> None:
        folder = self._require_order()
        if folder is None:
            return
        if messagebox.askyesno("ลบออเดอร์", f"ลบออเดอร์ {folder.name} และไฟล์ในโฟลเดอร์นี้?", icon="warning", parent=self):
            shutil.rmtree(folder, ignore_errors=True)
            self.current_order = None
            self._refresh_orders()

    def _build_crop_page(self, parent: ttk.Frame) -> None:
        holder = ttk.Frame(parent)
        holder.pack(fill="x", anchor="n")
        self._build_custom_a4_crop_panel(holder)

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

    def _build_cover_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        number_box = ttk.Frame(body)
        number_box.pack(side="left", fill="both", expand=True)

        chooser = ttk.Frame(number_box)
        chooser.pack(fill="x", pady=(0, 6))
        ttk.Label(
            chooser,
            text="แบบปก",
            font=("Segoe UI", 9, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack(side="left")
        self.cover_template_combo = ttk.Combobox(
            chooser,
            textvariable=self.cover_template_var,
            values=list(self.cover_template_labels),
            state="readonly",
            width=30,
        )
        self.cover_template_combo.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.cover_template_combo.bind("<<ComboboxSelected>>", self._on_cover_template_changed)
        ttk.Button(chooser, text="สุ่มปก", command=self.randomize_cover_template).pack(side="left")

        info = tk.Frame(number_box, bg=UI_SURFACE, highlightthickness=1, highlightbackground=UI_BORDER, padx=14, pady=12)
        info.pack(fill="x")
        self.cover_eye_var = tk.StringVar(value="ยังไม่ได้เลือกลายตา")
        tk.Label(info, textvariable=self.cover_eye_var, font=("Segoe UI", 11, "bold"), fg=UI_ACCENT_DARK,
                 bg=UI_SURFACE).pack(anchor="w")
        tk.Label(
            info,
            text="เลือกลายตา: คลิกขวาที่ลายในหน้า A4 → ส่งไปหน้าปก",
            font=("Segoe UI", 9),
            fg=UI_MUTED,
            bg=UI_SURFACE,
        ).pack(anchor="w", pady=(2, 10))
        self.cover_ai_button = tk.Button(
            info,
            text="✨ เจนปกใหม่ด้วย AI",
            command=self.generate_ai_cover,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            pady=6,
            cursor="hand2",
        )
        self.cover_ai_button.pack(fill="x")
        self.cover_ai_status_var = tk.StringVar(value="ได้ปกแบบใหม่ ไม่ซ้ำของเดิม • เซฟขึ้น GitHub ให้อัตโนมัติ")
        tk.Label(info, textvariable=self.cover_ai_status_var, font=("Segoe UI", 9), fg=UI_MUTED, bg=UI_SURFACE,
                 wraplength=380, justify="left").pack(anchor="w", pady=(6, 0))

        preview = ttk.Frame(body, padding=(8, 0, 0, 0))
        preview.pack(side="right", fill="y")
        ttk.Label(
            preview,
            text="รูปปก  •  ตัวอย่างตา",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack()
        self.cover_preview_label = ttk.Label(preview, anchor="center")
        self.cover_preview_label.pack(pady=(6, 8))
        ttk.Button(preview, text="โฟลเดอร์", command=self.open_cover_output_folder).pack(
            fill="x", pady=(0, 8)
        )
        tk.Button(
            preview,
            text="บันทึกรูปตัวอย่าง",
            command=self.generate_cover,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        ).pack(fill="x")

    def _build_ai_options(self, form: ttk.Frame) -> tk.Text:
        options = ttk.Frame(form)
        options.pack(fill="x", pady=(0, 10))
        ttk.Label(options, text="สไตล์ภาพ", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Combobox(
            options,
            textvariable=self.ai_style_var,
            values=list(STYLE_PROMPTS),
            state="readonly",
            width=22,
        ).pack(side="left", padx=(6, 14))
        ttk.Label(options, text="พื้นหลังโปร่งใส", style="Muted.TLabel").pack(side="left")

        design_row = ttk.Frame(form)
        design_row.pack(fill="x", pady=(0, 10))
        ttk.Label(design_row, text="ลายม่านตา", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Combobox(
            design_row,
            textvariable=self.ai_design_var,
            values=list(DESIGN_PROMPTS),
            state="readonly",
            width=24,
        ).pack(side="left", padx=(6, 14))
        ttk.Button(design_row, text="สุ่มทั้งหมด", command=self.randomize_ai_options).pack(side="left")

        color_row = ttk.Frame(form)
        color_row.pack(fill="x", pady=(0, 10))
        ttk.Label(color_row, text="สีหลัก", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Combobox(
            color_row,
            textvariable=self.ai_primary_color_var,
            values=list(COLOR_PROMPTS),
            state="readonly",
            width=11,
        ).pack(side="left", padx=(6, 14))
        ttk.Label(color_row, text="สีรอง", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Combobox(
            color_row,
            textvariable=self.ai_secondary_color_var,
            values=list(COLOR_PROMPTS),
            state="readonly",
            width=11,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            form,
            text="รายละเอียดเพิ่ม (ไม่ใส่ก็ได้)",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack(anchor="w")
        prompt_text = tk.Text(
            form,
            height=3,
            wrap="word",
            bg=UI_SURFACE,
            fg=UI_TEXT,
            relief="solid",
            bd=1,
            font=("Segoe UI", 10),
        )
        prompt_text.pack(fill="x", pady=(6, 10))
        return prompt_text

    def _build_ai_single_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        form = ttk.Frame(body)
        form.grid(row=0, column=0, sticky="nsew", padx=(4, 16))
        self.ai_single_prompt_text = self._build_ai_options(form)
        reference_row = ttk.Frame(form)
        reference_row.pack(fill="x", pady=(0, 8))
        self.ai_reference_button = ttk.Button(
            reference_row,
            text="แนบรูปอ้างอิง",
            command=self._choose_ai_reference_image,
        )
        self.ai_reference_button.pack(side="left")
        self.ai_reference_paste_button = ttk.Button(
            reference_row,
            text="วางรูป",
            command=self._paste_ai_reference_image,
        )
        self.ai_reference_paste_button.pack(side="left", padx=(6, 0))
        self.ai_reference_name_var = tk.StringVar(value="ยังไม่ได้แนบรูป")
        ttk.Label(
            reference_row,
            textvariable=self.ai_reference_name_var,
            style="Muted.TLabel",
        ).pack(side="left", padx=8, fill="x", expand=True)
        self.ai_reference_remove_button = ttk.Button(
            reference_row,
            text="เอาออก",
            command=self._clear_ai_reference_image,
            state="disabled",
        )
        self.ai_reference_remove_button.pack(side="right")
        ttk.Label(
            form,
            text="วางรูปที่แคปไว้หรือแนบไฟล์ แล้วระบุเฉพาะส่วนที่ต้องการเปลี่ยน",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        self.ai_generate_button = tk.Button(
            form,
            text="สร้าง 1 คู่",
            command=self.generate_ai_eye,
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        self.ai_generate_button.pack(fill="x")
        ttk.Label(form, textvariable=self.ai_single_status_var, style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        result_row = ttk.Frame(form)
        result_row.pack(fill="x", pady=(6, 0))
        ttk.Button(result_row, text="เพิ่มเข้า Data แบบที่หนึ่ง", command=self._ai_result_to_data).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(result_row, text="ส่งเข้ากล่องครอป A4", command=self._ai_result_to_crop).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )
        ttk.Button(result_row, text="เพิ่มลงหน้า 4×6", command=self._ai_result_to_4x6).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )
        self.ai_customer_link_button = tk.Button(
            form,
            text="OFF  ลิงก์ลูกค้า: ปิด",
            command=self.toggle_customer_portal,
            bg="#E8EFEB",
            fg=UI_MUTED,
            activebackground="#DCE9E1",
            activeforeground=UI_TEXT,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=10,
            pady=8,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        self.ai_customer_link_button.pack(fill="x", pady=(10, 0))
        portal_link_row = tk.Frame(form, bg=UI_BG)
        portal_link_row.pack(fill="x", pady=(6, 0))
        ttk.Label(portal_link_row, text="ลิงก์").pack(side="left", padx=(0, 6))
        self.portal_link_entry = ttk.Entry(portal_link_row, textvariable=self.portal_url_var, state="readonly")
        self.portal_link_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(portal_link_row, text="คัดลอก", command=self._copy_customer_portal_link).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(form, textvariable=self.portal_status_var, style="Muted.TLabel").pack(
            anchor="w", pady=(5, 0)
        )
        self._refresh_portal_controls()
        self._build_ai_preview(body, "single")

    def _build_ai_collection_page(self, parent: ttk.Frame) -> None:
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        form = ttk.Frame(body)
        form.grid(row=0, column=0, sticky="nsew", padx=(4, 16))
        self.ai_collection_prompt_text = self._build_ai_options(form)
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
        self.ai_preset_button.pack(fill="x")

        ttk.Label(
            form,
            text="Process / แผนชุด 16 คู่",
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
            text="ยืนยันแผนนี้ • เริ่มสร้าง 16 คู่",
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
        ttk.Label(form, textvariable=self.ai_collection_status_var, style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        self._build_ai_preview(body, "collection")

    def _build_ai_preview(self, body: ttk.Frame, target: str) -> None:
        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky="n", padx=(0, 4))
        ttk.Label(
            preview,
            text="AI Preview",
            font=("Segoe UI", 10, "bold"),
            foreground=UI_ACCENT_DARK,
        ).pack()
        label = tk.Label(
            preview,
            bg="white",
            bd=1,
            relief="solid",
            highlightthickness=0,
        )
        label.pack(pady=(6, 8))
        setattr(self, f"ai_{target}_preview_label", label)
        self._set_ai_preview(Image.new("RGBA", (240, 240), (255, 255, 255, 0)), target)
        ttk.Button(preview, text="เปิดโฟลเดอร์", command=self.open_ai_output_folder).pack(fill="x")
        if target == "single":
            ttk.Label(
                preview,
                text="แก้ไขรูปล่าสุด",
                font=("Segoe UI", 9, "bold"),
                foreground=UI_ACCENT_DARK,
            ).pack(anchor="w", pady=(10, 2))
            self.ai_edit_prompt_text = tk.Text(
                preview,
                height=2,
                width=29,
                wrap="word",
                bg=UI_SURFACE,
                fg=UI_TEXT,
                relief="solid",
                bd=1,
                font=("Segoe UI", 9),
            )
            self.ai_edit_prompt_text.pack(fill="x", pady=(0, 5))
            self.ai_edit_button = tk.Button(
                preview,
                text="แก้ไขรูปนี้",
                command=self.edit_ai_eye,
                bg=UI_ACCENT_DARK,
                fg="white",
                activebackground=UI_ACCENT,
                activeforeground="white",
                font=("Segoe UI", 9, "bold"),
                relief="flat",
                padx=8,
                pady=7,
                cursor="hand2",
                bd=0,
                highlightthickness=0,
                state="disabled",
            )
            self.ai_edit_button.pack(fill="x")

    def _set_ai_preview(self, image: Image.Image, target: str) -> None:
        preview = ImageOps.contain(image.convert("RGBA"), (216, 216), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (240, 240), (238, 238, 238, 255))
        draw = ImageDraw.Draw(canvas)
        tile = 16
        for y in range(0, 240, tile):
            for x in range(0, 240, tile):
                if (x // tile + y // tile) % 2:
                    draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(255, 255, 255, 255))
        canvas.alpha_composite(preview, ((240 - preview.width) // 2, (240 - preview.height) // 2))
        photo = ImageTk.PhotoImage(canvas)
        setattr(self, f"ai_{target}_preview_photo", photo)
        getattr(self, f"ai_{target}_preview_label").configure(image=photo)

    def output_ai_dir(self) -> Path:
        return Path(self.source_var.get()).parent / "AI_Eyes"

    def open_ai_output_folder(self) -> None:
        folder = self.output_ai_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def open_customer_portal(self) -> None:
        if self.customer_portal is not None and self.customer_portal.is_running:
            self._refresh_portal_controls()
            return
        try:
            self.portal_status_var.set("กำลังเปิดลิงก์ชั่วคราว...")
            self.customer_portal = CustomerPortal(
                on_public_url=lambda url: self.after(0, self._customer_portal_url_ready, url),
                on_generate_request=lambda job_id, payload: self.after(
                    0, self._handle_portal_generate_request, job_id, payload
                ),
                on_selection_saved=self._notify_customer_selection_saved,
                save_root=self.customer_portal_output_dir(),
            )
            local_url = self.customer_portal.start()
            self.portal_url_var.set(local_url)
            self.portal_status_var.set("เปิดหน้าออกแบบแล้ว • กำลังขอลิงก์สาธารณะ...")
            self._refresh_portal_controls()
        except Exception as exc:
            self.customer_portal = None
            self.portal_status_var.set("เปิดลิงก์ไม่สำเร็จ")
            self.portal_url_var.set("ปิดอยู่ — ยังไม่มีลิงก์ใช้งาน")
            self._refresh_portal_controls()
            messagebox.showerror("ลิงก์ลูกค้า", str(exc))

    def customer_portal_output_dir(self) -> Path:
        return Path(self.source_var.get()).parent / "ลูกค้าเลือกจากลิงก์"

    def _handle_portal_generate_request(self, job_id: str, payload: dict[str, object]) -> None:
        portal = self.customer_portal
        if portal is None or not portal.is_running:
            return
        self.portal_status_var.set("ลูกค้าส่งคำสั่งแล้ว • โปรแกรมกำลังสร้างพรีวิว...")
        self._set_ai_busy(True)
        threading.Thread(
            target=self._portal_generate_worker,
            args=(portal, job_id, payload),
            daemon=True,
        ).start()

    def _portal_generate_worker(
        self,
        portal: CustomerPortal,
        job_id: str,
        payload: dict[str, object],
    ) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="blythe_customer_remote_") as temp_dir:
                reference_bytes = payload.get("_reference_image_bytes")
                reference_image = None
                if isinstance(reference_bytes, bytes):
                    reference_image = Path(temp_dir) / "customer_reference.png"
                    reference_image.write_bytes(reference_bytes)
                _path, image = create_eye(
                    str(payload.get("notes") or ""),
                    Path(temp_dir),
                    style=str(payload.get("style") or "อัตโนมัติ"),
                    background="โปร่งใส",
                    design=str(payload.get("design") or "อัตโนมัติ"),
                    color_primary=str(payload.get("primary") or "อัตโนมัติ"),
                    color_secondary=str(payload.get("secondary") or "อัตโนมัติ"),
                    reference_image=reference_image,
                )
            metadata = {key: value for key, value in payload.items() if not key.startswith("_")}
            portal.complete_generation(job_id, image, metadata)
            self.after(0, self.portal_status_var.set, "สร้างพรีวิวจากคำสั่งลูกค้าแล้ว")
        except Exception:
            portal.fail_generation(job_id)
            self.after(0, self.portal_status_var.set, "โปรแกรมสร้างพรีวิวลูกค้าไม่สำเร็จ")
        finally:
            self.after(0, self._set_ai_busy, False)

    def toggle_customer_portal(self) -> None:
        if self.customer_portal is not None and self.customer_portal.is_running:
            self.close_customer_portal()
        else:
            self.open_customer_portal()

    def _refresh_portal_controls(self) -> None:
        is_on = self.customer_portal is not None and self.customer_portal.is_running
        if hasattr(self, "ai_customer_link_button"):
            self.ai_customer_link_button.configure(
                text=("ON   ลิงก์ลูกค้า: เปิดอยู่" if is_on else "OFF  ลิงก์ลูกค้า: ปิดอยู่"),
                bg=(UI_ACCENT if is_on else "#E8EFEB"),
                fg=("white" if is_on else UI_MUTED),
                activebackground=(UI_ACCENT_DARK if is_on else "#DCE9E1"),
                activeforeground="white" if is_on else UI_TEXT,
            )

    def _customer_portal_url_ready(self, url: str) -> None:
        if self.customer_portal is None or not self.customer_portal.is_running:
            return
        self.portal_url_var.set(url)
        if self._last_ntfy_customer_url == url:
            self.portal_status_var.set("ลิงก์สาธารณะพร้อม • ส่งไป ntfy แล้ว")
            self._refresh_portal_controls()
            return
        self._last_ntfy_customer_url = url
        self.portal_status_var.set("ลิงก์พร้อม • กำลังส่งแจ้งเตือนไป ntfy...")
        self._refresh_portal_controls()
        threading.Thread(
            target=self._send_customer_url_to_ntfy,
            args=(url,),
            daemon=True,
        ).start()

    def _send_customer_url_to_ntfy(self, url: str) -> None:
        request = urllib.request.Request(
            CUSTOMER_LINK_NTFY_URL,
            data=f"ลิงก์ออกแบบตาสำหรับลูกค้า\n{url}".encode("utf-8"),
            headers={"Title": "Blythe Eye customer link", "Click": url},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8):
                pass
        except Exception as exc:
            self.after(
                0,
                self.portal_status_var.set,
                f"ลิงก์พร้อมแล้ว แต่ส่ง ntfy ไม่สำเร็จ: {exc}",
            )
            return
        self.after(0, self.portal_status_var.set, "ลิงก์สาธารณะพร้อม • ส่งไป ntfy แล้ว")

    def _notify_customer_selection_saved(self, customer: str, folder: Path) -> None:
        message = f"ลูกค้าบันทึกแบบตาแล้ว\nลูกค้า: {customer}\nรายการ: {folder.name}"
        request = urllib.request.Request(
            CUSTOMER_LINK_NTFY_URL,
            data=message.encode("utf-8"),
            headers={"Title": "Blythe Eye customer saved"},
            method="POST",
        )
        threading.Thread(
            target=self._post_customer_save_notification,
            args=(request,),
            name="blythe-customer-save-notification",
            daemon=True,
        ).start()

    @staticmethod
    def _post_customer_save_notification(request: urllib.request.Request) -> None:
        try:
            with urllib.request.urlopen(request, timeout=8):
                pass
        except Exception:
            pass

    def _copy_customer_portal_link(self) -> None:
        url = self.portal_url_var.get().strip()
        if not url:
            return
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update()
        self.portal_status_var.set("คัดลอกลิงก์แล้ว")

    def close_customer_portal(self) -> None:
        if self.customer_portal is not None:
            self.customer_portal.stop()
            self.customer_portal = None
        self.portal_url_var.set("")
        self.portal_url_var.set("ปิดอยู่ — ยังไม่มีลิงก์ใช้งาน")
        self.portal_status_var.set("ปิดอยู่")
        self._refresh_portal_controls()

    def _on_close(self) -> None:
        if self.customer_portal is not None:
            self.customer_portal.stop()
            self.customer_portal = None
        if self.ai_reference_temp_path is not None:
            self.ai_reference_temp_path.unlink(missing_ok=True)
        self.custom_a4_temp.cleanup()
        self.destroy()

    def randomize_ai_options(self) -> None:
        styles = [value for value in STYLE_PROMPTS if value != "อัตโนมัติ"]
        designs = [value for value in DESIGN_PROMPTS if value != "อัตโนมัติ"]
        colors = [value for value in COLOR_PROMPTS if value != "อัตโนมัติ"]
        self.ai_style_var.set(random.choice(styles))
        self.ai_design_var.set(random.choice(designs))
        primary, secondary = random.sample(colors, 2)
        self.ai_primary_color_var.set(primary)
        self.ai_secondary_color_var.set(secondary)
        status = (
            self.ai_collection_status_var
            if self.current_page == "ai_collection"
            else self.ai_single_status_var
        )
        status.set("สุ่มตัวเลือกแล้ว")

    def _set_ai_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.ai_generate_button.configure(state=state)
        self.ai_preset_button.configure(state=state)
        if hasattr(self, "ai_reference_button"):
            self.ai_reference_button.configure(state=state)
            self.ai_reference_paste_button.configure(state=state)
            self.ai_reference_remove_button.configure(
                state=("normal" if not busy and self.ai_reference_image else "disabled")
            )
        self.ai_generate_preset_button.configure(
            state=("disabled" if busy or self.ai_collection_plan is None else "normal")
        )
        if hasattr(self, "ai_edit_button"):
            self.ai_edit_button.configure(
                state=("normal" if not busy and self.ai_image_path is not None else "disabled")
            )

    def generate_ai_eye(self) -> None:
        prompt = self.ai_single_prompt_text.get("1.0", "end").strip()
        style = self.ai_style_var.get()
        background = self.ai_background_var.get()
        design = self.ai_design_var.get()
        color_primary = self.ai_primary_color_var.get()
        color_secondary = self.ai_secondary_color_var.get()
        reference_image = self.ai_reference_image
        self._set_ai_busy(True)
        self.ai_single_status_var.set(
            "กำลังปรับจากรูปอ้างอิง..." if reference_image else "กำลังสร้าง 1 คู่..."
        )
        threading.Thread(
            target=self._generate_ai_eye_worker,
            args=(prompt, style, background, design, color_primary, color_secondary, reference_image),
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
        reference_image: Path | None = None,
        action: str = "สร้าง",
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
                reference_image=reference_image,
                conversation_state=self.ai_single_conversation_state,
            )
        except Exception as exc:
            self.after(0, self._finish_ai_eye_error, str(exc), action)
            return
        self.after(0, self._finish_ai_eye_success, path, image, action)

    def edit_ai_eye(self) -> None:
        if self.ai_image_path is None or not self.ai_image_path.is_file():
            self.ai_single_status_var.set("ยังไม่มีรูปล่าสุดให้แก้ไข")
            return
        prompt = self.ai_edit_prompt_text.get("1.0", "end").strip()
        if not prompt:
            self.ai_single_status_var.set("พิมพ์สิ่งที่ต้องการแก้ไขก่อน")
            self.ai_edit_prompt_text.focus_set()
            return
        reference_image = self.ai_image_path
        self._set_ai_busy(True)
        self.ai_single_status_var.set("กำลังแก้ไขรูปล่าสุด...")
        threading.Thread(
            target=self._generate_ai_eye_worker,
            args=(
                prompt,
                "อัตโนมัติ",
                "โปร่งใส",
                "อัตโนมัติ",
                "อัตโนมัติ",
                "อัตโนมัติ",
                reference_image,
                "แก้ไข",
            ),
            daemon=True,
        ).start()

    def _choose_ai_reference_image(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="เลือกรูปตาอ้างอิง",
            filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.webp *.bmp"), ("ทุกไฟล์", "*.*")],
        )
        if not filename:
            return
        self._set_ai_reference_image(Path(filename))

    def _set_ai_reference_image(self, reference_image: Path, temporary: bool = False) -> None:
        try:
            with Image.open(reference_image) as opened:
                preview = opened.convert("RGBA").copy()
        except Exception as exc:
            if temporary:
                reference_image.unlink(missing_ok=True)
            messagebox.showerror("รูปอ้างอิง", f"เปิดรูปนี้ไม่ได้: {exc}", parent=self)
            return
        old_temporary = self.ai_reference_temp_path
        self.ai_reference_image = reference_image
        self.ai_reference_temp_path = reference_image if temporary else None
        if old_temporary is not None and old_temporary != reference_image:
            old_temporary.unlink(missing_ok=True)
        self.ai_reference_name_var.set(reference_image.name)
        self.ai_reference_remove_button.configure(state="normal")
        self._set_ai_preview(preview, "single")
        self.ai_single_status_var.set("แนบรูปแล้ว • พิมพ์สิ่งที่ต้องการเปลี่ยนได้")

    def _on_ai_reference_paste_shortcut(self, event):
        if self.current_page != "ai_single":
            return None
        focus = self.focus_get()
        if isinstance(focus, (tk.Text, tk.Entry, tk.Spinbox, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return None
        return self._paste_ai_reference_image(show_empty_message=False)

    def _paste_ai_reference_image(self, show_empty_message: bool = True):
        try:
            clipboard = ImageGrab.grabclipboard()
        except Exception as exc:
            self.ai_single_status_var.set("อ่านรูปจากคลิปบอร์ดไม่ได้")
            if show_empty_message:
                messagebox.showerror("วางรูปอ้างอิง", str(exc), parent=self)
            return "break"

        if isinstance(clipboard, Image.Image):
            with tempfile.NamedTemporaryFile(prefix="blythe_eye_ref_", suffix=".png", delete=False) as temp:
                reference_image = Path(temp.name)
            try:
                clipboard.save(reference_image, format="PNG")
            except Exception as exc:
                reference_image.unlink(missing_ok=True)
                self.ai_single_status_var.set("บันทึกรูปจากคลิปบอร์ดไม่ได้")
                if show_empty_message:
                    messagebox.showerror("วางรูปอ้างอิง", str(exc), parent=self)
                return "break"
            self._set_ai_reference_image(reference_image, temporary=True)
            return "break"

        if isinstance(clipboard, list) and clipboard:
            self._set_ai_reference_image(Path(clipboard[0]))
            return "break"

        self.ai_single_status_var.set("คลิปบอร์ดยังไม่มีรูป • คัดลอกรูปหรือแคปหน้าจอก่อน")
        if show_empty_message:
            messagebox.showinfo(
                "วางรูปอ้างอิง",
                "ยังไม่พบรูปในคลิปบอร์ด\nคัดลอกรูปหรือแคปหน้าจอ แล้วกด “วางรูป” หรือ Ctrl+V",
                parent=self,
            )
        return "break" if show_empty_message else None

    def _clear_ai_reference_image(self) -> None:
        self.ai_reference_image = None
        if self.ai_reference_temp_path is not None:
            self.ai_reference_temp_path.unlink(missing_ok=True)
            self.ai_reference_temp_path = None
        self.ai_reference_name_var.set("ยังไม่ได้แนบรูป")
        self.ai_reference_remove_button.configure(state="disabled")
        preview = (
            self.ai_image
            if self.ai_image is not None
            else Image.new("RGBA", (240, 240), (255, 255, 255, 0))
        )
        self._set_ai_preview(preview, "single")

    def _finish_ai_eye_success(self, path: Path, image: Image.Image, action: str = "สร้าง") -> None:
        self.ai_image_path = path
        self.ai_image = image
        self._set_ai_preview(image, "single")
        if action == "แก้ไข":
            self.ai_edit_prompt_text.delete("1.0", "end")
        self.ai_single_status_var.set(f"{action}เสร็จ • เก็บไว้ใน AI_Eyes • {path.name}")
        self._set_ai_busy(False)

    def _finish_ai_eye_error(self, message: str, action: str = "สร้าง 1 คู่") -> None:
        status = "แก้ไขรูปล่าสุดไม่สำเร็จ" if action == "แก้ไข" else "สร้าง 1 คู่ไม่สำเร็จ"
        title = "AI • แก้ไขรูปล่าสุด" if action == "แก้ไข" else "AI 1 คู่"
        self.ai_single_status_var.set(status)
        self._set_ai_busy(False)
        messagebox.showerror(title, message)

    def _finish_ai_collection_error(self, message: str) -> None:
        self.ai_collection_status_var.set("สร้างชุด 16 คู่ไม่สำเร็จ")
        self._set_ai_busy(False)
        messagebox.showerror("AI 16 คู่", message)

    def generate_ai_preset(self) -> None:
        prompt = self.ai_collection_prompt_text.get("1.0", "end").strip()
        style = self.ai_style_var.get()
        design = self.ai_design_var.get()
        color_primary = self.ai_primary_color_var.get()
        color_secondary = self.ai_secondary_color_var.get()
        self.ai_collection_plan = None
        self.ai_collection_prompt = prompt
        self._show_ai_plan_text("")
        self._append_ai_log("STEP 1 • รับค่าจากหน้า AI แล้ว")
        self._append_ai_log(f"  สไตล์: {style}")
        self._append_ai_log(f"  ลายม่านตา: {design}")
        self._append_ai_log(f"  สีหลัก: {color_primary}  •  สีรอง: {color_secondary}")
        if prompt:
            self._append_ai_log(f"  รายละเอียดเพิ่ม: {prompt}")
        self._append_ai_log("")
        self._append_ai_log("STEP 2 • ส่งให้ GPT วางคอนเซ็ปต์ + palette + รายการ 1–16")
        self._append_ai_log("  กำลังรอ GPT ตอบ... ยังไม่สร้างรูปภาพ")
        self._set_ai_busy(True)
        self.ai_collection_status_var.set("กำลังวางแผนชุด 16 คู่...")
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
            self.after(0, self._append_ai_log, f"ERROR • วางแผนไม่สำเร็จ: {exc}")
            self.after(0, self._finish_ai_collection_error, str(exc))
            return
        self.after(0, self._append_ai_log, "STEP 3 • GPT ส่งแผนกลับมาแล้ว และผ่านการตรวจ 16 คู่")
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

    def _append_ai_log(self, text: str) -> None:
        self.ai_plan_text.configure(state="normal")
        if self.ai_plan_text.index("end-1c") != "1.0":
            self.ai_plan_text.insert("end", "\n")
        self.ai_plan_text.insert("end", text)
        self.ai_plan_text.see("end")
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
        self._append_ai_log("")
        self._append_ai_log("========== แผนที่รอคุณ CONFIRM ==========")
        self._append_ai_log(self._format_ai_plan(plan))
        self._append_ai_log("")
        self._append_ai_log("STEP 4 • ยังไม่สร้างรูป — อ่านแผนด้านบนก่อน")
        self._append_ai_log("  ถ้าโอเค: กด “ยืนยันแผนนี้ • เริ่มสร้าง 16 คู่”")
        self._append_ai_log("  ถ้าไม่โอเค: แก้ตัวเลือก/รายละเอียด แล้วกด “วางแผนใหม่ 16 คู่”")
        self.ai_preset_button.configure(text="วางแผนใหม่ 16 คู่")
        self.ai_collection_status_var.set("รอคุณยืนยันแผน • ยังไม่สร้างรูป")
        self._set_ai_busy(False)

    def generate_ai_preset_from_plan(self) -> None:
        if self.ai_collection_plan is None or self.ai_collection_state is None:
            self.ai_collection_status_var.set("กรุณาวางแผนชุดก่อน")
            return
        self._append_ai_log("")
        self._append_ai_log("CONFIRM • ผู้ใช้ยืนยันแผนแล้ว เริ่มสร้างตามรายการ 1–16")
        self._append_ai_log("  เริ่มประวัติสร้างภาพใหม่สำหรับชุดนี้ • คู่ 01–16 จะอยู่ในประวัติภาพเดียวกัน")
        image_conversation_state: dict[str, str] = {}
        self._set_ai_busy(True)
        self.ai_collection_status_var.set("กำลังสร้าง 1/16...")
        threading.Thread(
            target=self._generate_ai_preset_worker,
            args=(
                self.ai_collection_plan,
                image_conversation_state,
                self.ai_collection_prompt,
                self.output_ai_dir(),
            ),
            daemon=True,
        ).start()

    def _generate_ai_preset_worker(
        self,
        plan: dict,
        conversation_state: dict[str, str],
        prompt: str,
        output_root: Path,
    ) -> None:
        def progress(message: str) -> None:
            self.after(0, self.ai_collection_status_var.set, message)
            self.after(0, self._append_ai_log, message)

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
            sheet_path = preset_dir / f"AI_Preset_{safe_name}_{stamp}_4x6.png"
            build_ai_preset_sheet(images, sheet_path)
        except Exception as exc:
            self.after(0, self._finish_ai_collection_error, str(exc))
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
        self._set_ai_preview(image, "collection")
        self.ai_collection_status_var.set(f"กำลังสร้าง {index}/16 • conversation เดียว")
        self._append_ai_log(f"  ✓ คู่ {index:02d}/16 เสร็จแล้ว • {path.name}")

    def _finish_ai_preset_success(
        self,
        sheet_path: Path,
        preset_dir: Path,
        last_path: Path,
        last_image: Image.Image,
    ) -> None:
        self.ai_image_path = last_path
        self.ai_image = last_image
        self._set_ai_preview(last_image, "collection")
        self.ai_collection_status_var.set(f"ชุด 16 คู่พร้อม • {preset_dir.name}")
        self._append_ai_log("จัดหน้า 4×6 เสร็จแล้ว • เก็บไว้ใน AI_Eyes เท่านั้น")
        self._append_ai_log(f"DONE • ชุด 16 คู่พร้อมให้เลือกภายหลัง • {preset_dir.name}")
        self._set_ai_busy(False)

    def _show_page(self, page: str) -> None:
        page = page if page in self.pages else "a4"
        self.current_page = page
        for name, frame in self.pages.items():
            frame.pack_forget()
            active = name == page
            self.nav_buttons[name].configure(bg=UI_ACCENT if active else UI_SURFACE, fg="white" if active else UI_TEXT)
        self.pages[page].pack(fill="both", expand=True)
        if page == "a4":
            self.show_preview()
        elif page == "4x6":
            self.show_4x6_preview()
        elif page == "cover":
            self.show_cover_preview()
        elif page == "orders":
            self._refresh_orders()

    def _on_mousewheel(self, event) -> None:
        if self.current_page == "4x6":
            canvas = self.six_number_canvas
        elif self.current_page == "a4":
            canvas = self.number_canvas
        else:
            return
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
        settings = load_user_settings()
        settings.update(
            {
                "source_folder": self.source_var.get(),
                "source_4x6_folder": self.source_4x6_var.get(),
            }
        )
        save_user_settings(settings)

    def _extra_sets(self) -> list[tuple[int, str, Path]]:
        """Enabled sets besides set 1 as (group, title, folder). Turned-off sets never show anywhere."""
        settings = load_user_settings()
        source = Path(self.source_var.get())
        sets = []
        sets.append((2, "แบบที่สอง", second_source_folder(source)))  # always on: designs for sale
        set3_folder = settings.get("set3_folder", "").strip()
        if settings.get("set3_enabled", "0") == "1" and set3_folder:
            sets.append((3, settings.get("set3_name", "").strip() or "แบบเพิ่มเติม", Path(set3_folder)))
        return sets

    def _data_sync_folders(self) -> dict[str, Path]:
        # Set 3 is a local-only folder, so it is never synced.
        folders = {"a4_set1": Path(self.source_var.get())}
        for group, _title, folder in self._extra_sets():
            if group == 2:
                folders["a4_set2"] = folder
        folders["sheets_4x6"] = Path(self.source_4x6_var.get())
        folders["covers"] = LIBRARY_COVERS
        return folders

    def _compare_data_sync(self, status_var: tk.StringVar) -> None:
        """Show how many images this computer and GitHub each have, and whether they match."""
        status_var.set("กำลังนับรูปในเครื่องกับบน GitHub…")
        folders = self._data_sync_folders()
        token = load_user_settings().get("github_token", "")
        names = {"a4_set1": "แบบที่หนึ่ง", "a4_set2": "แบบที่สอง", "sheets_4x6": "ไฟล์ตา 4×6", "covers": "ปก AI"}

        def worker() -> None:
            try:
                report = data_sync.compare(folders, DATA_SYNC_STATE_FILE, token)
            except Exception as exc:
                text = f"ตรวจไม่ได้: {exc}"
            else:
                lines = []
                for prefix, status in report.items():
                    line = f"{names.get(prefix, prefix)}:  ในเครื่อง {status.local}  •  GitHub {status.remote}  •  "
                    if status.in_sync:
                        line += "ตรงกัน ✓"
                    else:
                        parts = []
                        if status.only_local:
                            parts.append(f"มีแค่ในเครื่อง {status.only_local}")
                        if status.only_remote:
                            parts.append(f"มีแค่บน GitHub {status.only_remote}")
                        if status.different:
                            parts.append(f"ไฟล์ไม่เหมือนกัน {status.different}")
                        line += "ไม่ตรง ✗ (" + ", ".join(parts) + ") กด ซิงค์ตอนนี้"
                    lines.append(line)
                text = "\n".join(lines)
            try:
                self.after(0, lambda: status_var.set(text))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, name="blythe-data-compare", daemon=True).start()

    def _start_data_sync(self) -> None:
        """Sync the eye library with GitHub in the background."""
        if self._data_sync_running:
            self._data_sync_again = True
            return
        folders = self._data_sync_folders()
        if not folders["a4_set1"].is_dir():
            return
        self._data_sync_running = True
        self.sync_status_var.set("กำลังซิงค์กับ GitHub…")
        token = load_user_settings().get("github_token", "")

        def worker() -> None:
            try:
                result = data_sync.sync(folders, DATA_SYNC_STATE_FILE, token)
            except Exception as exc:
                result, error = None, str(exc)
            else:
                error = None
            try:
                self.after(0, self._finish_data_sync, result, error)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, name="blythe-data-sync", daemon=True).start()

    def _finish_data_sync(self, result: data_sync.SyncResult | None, error: str | None) -> None:
        self._data_sync_running = False
        self._data_sync_finished_once = True
        stamp = datetime.now().strftime("%H:%M")
        if error:
            self.sync_status_var.set(f"{stamp} ซิงค์ไม่สำเร็จ: {error}")
            if not self.design_ids:
                self.cache_var.set("โหลดลายตาจาก GitHub ไม่สำเร็จ • ตรวจอินเทอร์เน็ต")
        else:
            self.sync_status_var.set(f"{stamp} {result.summary()}")
            if result.local_changed or not self.design_ids:
                old_selections = self.selections.copy()
                old_history = list(self.selection_history)
                self.reload_assets()
                self.selections = OrderedDict(
                    (key, count) for key, count in old_selections.items() if key in self.assets
                )
                self.selection_history = [key for key in old_history if key in self.assets]
                self.refresh_selection_status()
                if any(path.startswith("sheets_4x6/") for path in result.downloaded + result.deleted_local):
                    self.reload_4x6_assets()
        if self._data_sync_again:
            self._data_sync_again = False
            self._start_data_sync()

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

        def browse_into(target: tk.StringVar, title: str) -> None:
            current = Path(target.get()) if target.get() else Path.home()
            initial = current if current.exists() else Path.home()
            selected = filedialog.askdirectory(parent=dialog, initialdir=str(initial), title=title)
            if selected:
                target.set(selected)

        def open_folder(folder: Path) -> None:
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer", str(folder)])

        ttk.Label(frame, text="ลายตา", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        library_row = ttk.Frame(frame)
        library_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        ttk.Label(
            library_row,
            text="แบบที่หนึ่ง แบบที่สอง และไฟล์ตา 4×6 เก็บในโปรแกรมและซิงค์กับ GitHub",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(library_row, text="เปิดโฟลเดอร์", command=lambda: open_folder(LIBRARY_DIR)).pack(side="right")

        saved = load_user_settings()
        set3_var = tk.StringVar(value=saved.get("set3_folder", ""))
        set3_name_var = tk.StringVar(value=saved.get("set3_name", "") or "แบบเพิ่มเติม")
        set3_on = tk.BooleanVar(value=saved.get("set3_enabled", "0") == "1")

        sets_frame = ttk.Frame(frame)
        sets_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        sets_frame.columnconfigure(1, weight=1)

        def toggle_button(row: int, enabled: tk.BooleanVar, hint: ttk.Label, note: str, widgets: list) -> None:
            toggle = ttk.Button(sets_frame, width=8)
            toggle.grid(row=row, column=3, padx=(6, 0), pady=2)

            def refresh() -> None:
                on = enabled.get()
                for widget in widgets:
                    widget.configure(state="normal" if on else "disabled")
                toggle.configure(text="✕ ปิด" if on else "＋ เปิด")
                hint.configure(text=note if on else "ปิดอยู่ • ไม่แสดงในโปรแกรม")

            def flip() -> None:
                enabled.set(not enabled.get())
                refresh()

            toggle.configure(command=flip)
            refresh()

        ttk.Label(sets_frame, text="แบบที่สอง", width=14).grid(row=0, column=0, sticky="w")
        ttk.Label(sets_frame, text="มีถาวร • ซิงค์กับ GitHub", style="Muted.TLabel").grid(
            row=0, column=1, columnspan=3, sticky="w"
        )

        set3_name = ttk.Entry(sets_frame, textvariable=set3_name_var, width=14)
        set3_name.grid(row=1, column=0, sticky="w", pady=(6, 0))
        set3_entry = ttk.Entry(sets_frame, textvariable=set3_var, width=34)
        set3_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        set3_browse = ttk.Button(
            sets_frame, text="เลือก...", command=lambda: browse_into(set3_var, "เลือกโฟลเดอร์ในเครื่อง")
        )
        set3_browse.grid(row=1, column=2, padx=(6, 0), pady=(6, 0))
        set3_hint = ttk.Label(sets_frame, style="Muted.TLabel")
        set3_hint.grid(row=2, column=1, columnspan=3, sticky="w")
        toggle_button(1, set3_on, set3_hint, "โฟลเดอร์ในเครื่อง • ไม่ซิงค์ขึ้น GitHub", [set3_entry, set3_browse])

        output_row = ttk.Frame(frame)
        output_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Label(output_row, text=f"ไฟล์งานลูกค้า: {DEFAULT_DATA_ROOT}", style="Muted.TLabel").pack(side="left")
        ttk.Button(output_row, text="เปิดโฟลเดอร์", command=lambda: open_folder(DEFAULT_DATA_ROOT)).pack(side="right")

        history_row = ttk.Frame(frame)
        history_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        history_status_var = tk.StringVar(value="ไม่กดปุ่มนี้: AI 1 คู่จะทำต่อในประวัติเดิม")
        ttk.Button(
            history_row,
            text="เริ่มประวัติ AI 1 คู่ใหม่",
            command=lambda: self._start_new_ai_history(history_status_var),
        ).pack(side="left")
        ttk.Label(
            history_row,
            textvariable=history_status_var,
            style="Muted.TLabel",
        ).pack(side="left", padx=8)

        update_row = ttk.Frame(frame)
        update_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        update_status_var = tk.StringVar(value=f"เวอร์ชันนี้ v{APP_VERSION} • กำลังเช็กเวอร์ชันล่าสุด…")
        ttk.Label(update_row, text="อัปเดตโปรแกรม", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(update_row, textvariable=update_status_var, style="Muted.TLabel").pack(side="left", padx=8)
        update_button = ttk.Button(
            update_row,
            text="อัปเดต",
            command=lambda: self._update_program_from_github(dialog, update_status_var, update_button),
        )
        update_button.pack(side="right")
        self._check_latest_version(update_status_var)

        sync_row = ttk.Frame(frame)
        sync_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Label(sync_row, text="ซิงค์ลายตากับ GitHub", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(sync_row, textvariable=self.sync_status_var, style="Muted.TLabel").pack(side="left", padx=8)
        token_var = tk.StringVar(value=load_user_settings().get("github_token", ""))

        def save_token() -> None:
            settings = load_user_settings()
            settings["github_token"] = token_var.get().strip()
            try:
                save_user_settings(settings)
            except OSError as exc:
                messagebox.showwarning("บันทึก token ไม่ได้", str(exc), parent=dialog)

        def sync_now() -> None:
            save_token()
            self._start_data_sync()

        ttk.Button(sync_row, text="ซิงค์ตอนนี้", command=sync_now).pack(side="right")
        ttk.Button(sync_row, text="ดูรูปบน GitHub", command=lambda: webbrowser.open(GITHUB_DATA_URL)).pack(
            side="right", padx=(0, 6)
        )
        compare_var = tk.StringVar(value="กำลังนับรูปในเครื่องกับบน GitHub…")
        compare_row = ttk.Frame(frame)
        compare_row.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(compare_row, textvariable=compare_var, style="Muted.TLabel", justify="left").pack(side="left")
        ttk.Button(compare_row, text="ตรวจอีกครั้ง", command=lambda: self._compare_data_sync(compare_var)).pack(
            side="right", anchor="n"
        )
        self._compare_data_sync(compare_var)

        token_row = ttk.Frame(frame)
        token_row.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(token_row, text="GitHub token (ใช้ตอนอัปรูปขึ้น)", style="Muted.TLabel").pack(side="left")
        ttk.Entry(token_row, textvariable=token_var, width=30, show="•").pack(side="left", padx=6)
        ttk.Button(token_row, text="วิธีสร้าง token", command=lambda: self._show_token_help(dialog)).pack(side="right")

        trash_row = ttk.Frame(frame)
        trash_row.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(trash_row, text="ถังขยะ", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(
            trash_row,
            text=f"รูปที่ลบไป {len(list_trash())} รูป • เก็บ {TRASH_KEEP_DAYS} วันแล้วลบเอง",
            style="Muted.TLabel",
        ).pack(side="left", padx=8)
        ttk.Button(trash_row, text="เปิดถังขยะ", command=lambda: self._open_trash(dialog)).pack(side="right")

        uninstall_row = ttk.Frame(frame)
        uninstall_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(uninstall_row, text="ถอนการติดตั้ง", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(
            uninstall_row,
            text="ลบโปรแกรมและไฟล์หลังบ้านทั้งหมด (ไฟล์งานลูกค้าไม่ถูกลบ)",
            style="Muted.TLabel",
        ).pack(side="left", padx=8)
        ttk.Button(uninstall_row, text="ถอนการติดตั้ง", command=lambda: self._uninstall_program(dialog)).pack(side="right")

        buttons = ttk.Frame(frame)
        buttons.grid(row=14, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="ยกเลิก", command=dialog.destroy).pack(side="left", padx=(0, 6))

        def save_and_close() -> None:
            set3_value = set3_var.get().strip()
            if set3_on.get() and (not set3_value or not Path(set3_value).expanduser().is_dir()):
                messagebox.showwarning("ไม่พบโฟลเดอร์", f"โฟลเดอร์ของ {set3_name_var.get().strip() or 'แบบเพิ่มเติม'} ไม่ถูกต้อง", parent=dialog)
                return
            settings = load_user_settings()
            settings.update(
                {
                    "set3_folder": str(Path(set3_value).expanduser().resolve()) if set3_value else "",
                    "set3_name": set3_name_var.get().strip(),
                    "set3_enabled": "1" if set3_on.get() else "0",
                }
            )
            try:
                save_user_settings(settings)
            except OSError as exc:
                messagebox.showwarning("บันทึกการตั้งค่าไม่ได้", str(exc), parent=dialog)
            save_token()

            dialog.grab_release()
            dialog.destroy()
            self.reload_assets()

        ttk.Button(buttons, text="บันทึก", command=save_and_close).pack(side="left")
        frame.columnconfigure(0, weight=1)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")

    def _show_token_help(self, parent: tk.Toplevel) -> None:
        messagebox.showinfo(
            "สร้าง GitHub token (ทำครั้งเดียวต่อเครื่อง)",
            "token ใช้ตอนอัปรูปขึ้น GitHub เท่านั้น ถ้าแค่โหลดรูปลงไม่ต้องมี\n\n"
            "1. ล็อกอิน GitHub ในหน้าที่จะเปิดขึ้น\n"
            "2. Token name: ตั้งชื่ออะไรก็ได้ เช่น Blythe\n"
            "3. Expiration: เลือก No expiration (หรือ 1 ปี)\n"
            "4. Repository access: เลือก Only select repositories → blythe-a4-maker\n"
            "5. หัวข้อ Permissions กด + Add permissions → เลือก Contents\n"
            "    แล้วเปลี่ยน Access จาก Read-only เป็น Read and write\n"
            "6. กด Generate token แล้วคัดลอกมาวางในช่อง GitHub token\n"
            "7. กด ซิงค์ตอนนี้ หรือ บันทึก\n\n"
            "อย่าส่ง token ให้คนอื่น เพราะใช้แก้ไฟล์ใน GitHub ของคุณได้",
            parent=parent,
        )
        webbrowser.open(GITHUB_TOKEN_URL)

    def _uninstall_targets(self, include_custom_library: bool) -> list[Path]:
        """Everything the app created: its hidden data folder, prepared caches and the program itself."""
        targets: list[Path] = [SETTINGS_DIR, LIBRARY_DIR.parent]
        source = Path(self.source_var.get()).expanduser()
        if source.is_dir():
            cache_roots = [source, *(path for path in source.parent.iterdir() if path.is_dir())]
            targets += [root / CACHE_DIR_NAME for root in cache_roots if (root / CACHE_DIR_NAME).is_dir()]
            if include_custom_library and (source / CUSTOM_A4_DIR_NAME).is_dir():
                targets.append(source / CUSTOM_A4_DIR_NAME)
        if getattr(sys, "frozen", False):
            targets.append(Path(sys.executable).resolve())
        else:
            app_root = Path(__file__).resolve().parents[1]
            if (app_root / "เปิดโปรแกรม.bat").is_file() and (app_root / "app" / "blythe_a4_maker.pyw").is_file():
                targets.append(app_root)
        return targets

    def _uninstall_program(self, dialog: tk.Toplevel) -> None:
        if not messagebox.askyesno(
            "ถอนการติดตั้ง",
            "ลบโปรแกรม Blythe Eye Maker ออกจากเครื่องแบบหมดจด?\n\n"
            f"• ไฟล์โปรแกรม\n• การตั้งค่าและไฟล์หลังบ้าน ({SETTINGS_DIR})\n• แคชที่โปรแกรมสร้าง ({CACHE_DIR_NAME})\n\n"
            "รูปต้นฉบับและไฟล์ A4/4×6 ที่ทำให้ลูกค้าจะไม่ถูกลบ",
            icon="warning",
            parent=dialog,
        ):
            return
        include_custom = messagebox.askyesno(
            "รูปคัสตอม",
            f"ลบรูปคัสตอมที่บันทึกไว้ ({CUSTOM_A4_DIR_NAME}) ด้วยไหม?\n\nกด No เพื่อเก็บไว้",
            parent=dialog,
        )
        targets = self._uninstall_targets(include_custom)
        script = (
            "param([int]$ProcessId, [string]$ListFile)\n"
            "$Targets = Get-Content -LiteralPath $ListFile -Encoding UTF8 | Where-Object { $_ }\n"
            "Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue\n"
            "$failed = @()\n"
            "foreach ($target in $Targets) {\n"
            "  $deadline = (Get-Date).AddSeconds(60)\n"
            "  while (Test-Path -LiteralPath $target) {\n"
            "    try { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop }\n"
            "    catch { if ((Get-Date) -gt $deadline) { $failed += $target; break }; Start-Sleep -Milliseconds 500 }\n"
            "  }\n"
            "}\n"
            "Add-Type -AssemblyName PresentationFramework\n"
            "if ($failed.Count) {\n"
            "  [System.Windows.MessageBox]::Show(('ลบไม่ได้บางรายการ:' + [Environment]::NewLine + ($failed -join [Environment]::NewLine)), 'Blythe Eye Maker') | Out-Null\n"
            "} else {\n"
            "  [System.Windows.MessageBox]::Show('ถอนการติดตั้ง Blythe Eye Maker เรียบร้อยแล้ว', 'Blythe Eye Maker') | Out-Null\n"
            "}\n"
            "Remove-Item -LiteralPath $ListFile, $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
        )
        uninstaller = Path(tempfile.gettempdir()) / f"blythe_uninstall_{os.getpid()}.ps1"
        target_list = uninstaller.with_suffix(".txt")
        try:
            uninstaller.write_text(script, encoding="utf-8-sig")
            target_list.write_text("\n".join(str(path) for path in targets), encoding="utf-8")
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(uninstaller),
                    "-ProcessId", str(os.getpid()), "-ListFile", str(target_list),
                ],
                creationflags=POWERSHELL_HELPER_FLAGS,
                close_fds=True,
                env=relaunch_environment(),
                cwd=tempfile.gettempdir(),
            )
        except OSError as exc:
            messagebox.showerror("ถอนการติดตั้งไม่สำเร็จ", str(exc), parent=dialog)
            return
        dialog.destroy()
        self._on_close()

    def _check_latest_version(self, status_var: tk.StringVar) -> None:
        """Show the running version and whether GitHub has a newer release."""

        def check() -> None:
            try:
                latest = str(github_release_info()["tag_name"])
            except Exception:
                message = f"เวอร์ชันนี้ v{APP_VERSION} • เช็กเวอร์ชันล่าสุดไม่ได้ (ไม่มีเน็ต?)"
            else:
                if version_tuple(latest) > version_tuple(APP_VERSION):
                    message = f"เวอร์ชันนี้ v{APP_VERSION} • มีเวอร์ชันใหม่ {latest} กดอัปเดตได้เลย"
                else:
                    message = f"เวอร์ชันนี้ v{APP_VERSION} • เป็นเวอร์ชันล่าสุดแล้ว ✓"
            try:
                self.after(0, lambda: status_var.set(message))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=check, name="blythe-version-check", daemon=True).start()

    def _update_program_from_github(
        self,
        dialog: tk.Toplevel,
        status_var: tk.StringVar,
        button: ttk.Button,
    ) -> None:
        if getattr(self, "_program_update_running", False):
            return
        if not messagebox.askyesno(
            "อัปเดตโปรแกรม",
            "ดาวน์โหลดไฟล์เวอร์ชันล่าสุดจาก GitHub เมื่อติดตั้งแล้วโปรแกรมจะปิดและเปิดใหม่ ต้องการดำเนินการหรือไม่?",
            parent=dialog,
        ):
            return

        self._program_update_running = True
        button.configure(state="disabled")
        status_var.set("กำลังดาวน์โหลดเวอร์ชันล่าสุด…")

        def download() -> None:
            work_dir = Path(tempfile.mkdtemp(prefix="blythe_update_"))
            try:
                if getattr(sys, "frozen", False):
                    update_file = download_latest_release_exe(work_dir)
                    self.after(0, lambda: self._finish_program_update(
                        dialog, status_var, button, work_dir, None, None, update_file
                    ))
                else:
                    archive = download_update_archive(work_dir)
                    source_dir = extract_update_archive(archive, work_dir)
                    self.after(0, lambda: self._finish_program_update(
                        dialog, status_var, button, work_dir, source_dir, None
                    ))
            except Exception as exc:
                shutil.rmtree(work_dir, ignore_errors=True)
                try:
                    self.after(0, lambda error=str(exc): self._finish_program_update(
                        dialog, status_var, button, work_dir, None, error
                    ))
                except tk.TclError:
                    pass

        threading.Thread(target=download, name="blythe-program-update", daemon=True).start()

    def _finish_program_update(
        self,
        dialog: tk.Toplevel,
        status_var: tk.StringVar,
        button: ttk.Button,
        work_dir: Path,
        source_dir: Path | None,
        error: str | None,
        update_file: Path | None = None,
    ) -> None:
        self._program_update_running = False
        if error or (source_dir is None and update_file is None):
            status_var.set("ดาวน์โหลดอัปเดตไม่สำเร็จ")
            if dialog.winfo_exists():
                button.configure(state="normal")
                messagebox.showerror("อัปเดตไม่สำเร็จ", error or "ไม่พบไฟล์โปรแกรม", parent=dialog)
            return
        if not dialog.winfo_exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            return
        if not messagebox.askyesno(
            "พร้อมติดตั้งอัปเดต",
            "ดาวน์โหลดเสร็จแล้ว โปรแกรมจะปิดเพื่อติดตั้งและเปิดใหม่อัตโนมัติ ต้องการติดตั้งตอนนี้หรือไม่?",
            parent=dialog,
        ):
            shutil.rmtree(work_dir, ignore_errors=True)
            status_var.set("ยกเลิกการติดตั้งอัปเดต")
            button.configure(state="normal")
            return

        frozen = getattr(sys, "frozen", False)
        try:
            if frozen:
                launch_exe_updater(os.getpid(), update_file, Path(sys.executable).resolve(), work_dir)
            else:
                self._launch_source_updater(source_dir, work_dir)
        except OSError as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            status_var.set("เริ่มตัวติดตั้งอัปเดตไม่ได้")
            button.configure(state="normal")
            messagebox.showerror("อัปเดตไม่สำเร็จ", str(exc), parent=dialog)
            return
        dialog.destroy()
        self.destroy()

    def _launch_source_updater(self, source_dir: Path, work_dir: Path) -> None:
        app_root = Path(__file__).resolve().parents[1]
        launcher = app_root / "เปิดโปรแกรม.bat"
        updater = Path(tempfile.gettempdir()) / f"blythe_apply_{os.getpid()}.ps1"
        script = (
            "param([int]$ProcessId, [string]$StageRoot, [string]$InstallRoot, [string]$WorkDir, [string]$Launcher)\n"
            "try {\n"
            "  Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction SilentlyContinue\n"
            "  Start-Sleep -Milliseconds 500\n"
            "  Get-ChildItem -LiteralPath $StageRoot -Force | Copy-Item -Destination $InstallRoot -Recurse -Force\n"
            "  Start-Process -FilePath $Launcher -WorkingDirectory $InstallRoot\n"
            "  Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue\n"
            "} catch {\n"
            "  Add-Type -AssemblyName PresentationFramework\n"
            "  [System.Windows.MessageBox]::Show(('ติดตั้งอัปเดตไม่สำเร็จ: ' + $_.Exception.Message), 'Blythe Eye Maker') | Out-Null\n"
            "}\n"
        )
        updater.write_text(script, encoding="utf-8-sig")
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater),
                "-ProcessId", str(os.getpid()), "-StageRoot", str(source_dir),
                "-InstallRoot", str(app_root), "-WorkDir", str(work_dir), "-Launcher", str(launcher),
            ],
            creationflags=POWERSHELL_HELPER_FLAGS,
            close_fds=True,
            env=relaunch_environment(),
        )

    def _start_new_ai_history(self, status_var: tk.StringVar) -> None:
        if str(self.ai_generate_button["state"]) == "disabled":
            status_var.set("รอให้การสร้างรูปปัจจุบันเสร็จก่อน")
            return
        self.ai_single_conversation_state.clear()
        status_var.set("ครั้งถัดไปจะเริ่มประวัติใหม่ • ประวัติเก่ายังอยู่")
        self.ai_single_status_var.set("ตั้งประวัติใหม่แล้ว • ใช้เมื่อกดสร้างครั้งถัดไป")

    def reload_assets(self) -> None:
        folder = Path(self.source_var.get())
        if folder.is_dir():
            try:
                migrate_custom_library(folder)
            except (OSError, ValueError):
                pass

        sets = [(1, "แบบที่หนึ่ง", folder), *self._extra_sets()]
        self.set_titles = {group: title for group, title, _folder in sets}
        self.assets = OrderedDict()
        self.prepared_assets = OrderedDict()
        self.design_ids = []
        # Group 0 holds unsaved crops, shown after set 1.
        group_ids: dict[int, list[str]] = {0: [], **{group: [] for group, _title, _folder in sets}}
        reused: list[str] = []
        rebuilt: list[str] = []
        failed: dict[str, str] = {}
        for group, _title, set_folder in sets:
            source_assets = discover_assets(set_folder)
            if not source_assets:
                continue
            prepared, stats = prepare_asset_cache(source_assets, set_folder)
            reused += list(stats.get("reused", []))
            rebuilt += list(stats.get("rebuilt", []))
            prefix = "" if group == 1 else f"แบบ{group}:"
            failed.update({f"{prefix}{key}": value for key, value in dict(stats.get("failed", {})).items()})
            for raw_id in visible_design_ids(source_assets):
                if raw_id not in prepared:
                    continue
                key = design_key(group, raw_id)
                self.assets[key] = source_assets[raw_id]
                self.prepared_assets[key] = prepared[raw_id]
                self.design_ids.append(key)
                group_ids[group].append(key)

        custom_items = discover_custom_a4_items(folder / CUSTOM_A4_DIR_NAME)
        custom_items.update(self.custom_a4_items)
        for custom_id, (source_path, chip_paths) in custom_items.items():
            self.assets[custom_id] = source_path
            self.prepared_assets[custom_id] = chip_paths
            group_ids[0].append(custom_id)

        self.cache_stats = {"reused": reused, "rebuilt": rebuilt, "failed": failed}

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
            button.bind("<Button-3>", lambda event, value=design_id: self._show_custom_a4_menu(event, value))
            self.number_buttons[design_id] = button

        row_cursor = 0
        # Unsaved crops (session only) follow set 1 instead of having their own section.
        set_one = group_ids[1] + group_ids[0]
        for index, design_id in enumerate(set_one):
            row_offset, col = divmod(index, columns)
            add_design_button(design_id, row_cursor + row_offset, col)

        if set_one:
            row_cursor += (len(set_one) + columns - 1) // columns

        for group in (group for group in group_ids if group > 1):
            if not group_ids[group]:
                continue
            ttk.Label(
                self.number_grid,
                text=self.set_titles[group],
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
            for index, design_id in enumerate(group_ids[group]):
                row_offset, col = divmod(index, columns)
                add_design_button(design_id, row_cursor + row_offset, col)
            row_cursor += (len(group_ids[group]) + columns - 1) // columns

        for col in range(columns):
            self.number_grid.columnconfigure(col, weight=1)

        self._reload_cover_buttons(group_ids)

        reused = len(self.cache_stats.get("reused", []))
        rebuilt = len(self.cache_stats.get("rebuilt", []))
        failed = len(self.cache_stats.get("failed", {}))
        cache_text = f"พร้อม {len(self.design_ids)} • เดิม {reused} • ทำใหม่ {rebuilt}"
        custom_count = len(group_ids[0])
        if custom_count:
            cache_text += f" • คัสตอม {custom_count}"
        if failed:
            cache_text += f" • ผิดพลาด {failed}"
        self.cache_var.set(cache_text)

        self.refresh_selection_status()
        self.show_preview()
        if not self.design_ids:
            messagebox.showwarning("ไม่พบลายตา", f"ไม่พบไฟล์ที่ชื่อเป็นหมายเลขใน\n{folder}")

        self.reload_4x6_assets()

    def _reload_cover_buttons(self, _group_ids: dict[int, list[str]]) -> None:
        if self.cover_selected_id not in self.prepared_assets:
            self.cover_selected_id = self.design_ids[0] if self.design_ids else None
        self.refresh_cover_selection()
        self.show_cover_preview()

    def select_cover_eye(self, design_id: str) -> None:
        self.cover_selected_id = design_id
        if self.cover_template_var.get() == self.cover_random_label:
            self._pick_random_cover_template()
        self.refresh_cover_selection()
        self.show_cover_preview()

    def refresh_cover_selection(self) -> None:
        if hasattr(self, "cover_eye_var"):
            self.cover_eye_var.set(
                f"ลายตาที่ใช้: {display_design_id(self.cover_selected_id)}" if self.cover_selected_id else "ยังไม่ได้เลือกลายตา"
            )

    def _send_design_to_cover(self, design_id: str) -> None:
        self.select_cover_eye(design_id)
        self._show_page("cover")

    def _reload_cover_templates(self, select_id: str | None = None) -> None:
        self.cover_templates = load_cover_templates()
        self.cover_template_labels = OrderedDict(
            [(self.cover_random_label, "__random__")]
            + [(str(item["label"]), template_id) for template_id, item in self.cover_templates.items()]
        )
        self.cover_template_combo.configure(values=list(self.cover_template_labels))
        if select_id in self.cover_templates:
            self.cover_template_var.set(str(self.cover_templates[select_id]["label"]))
        self.show_cover_preview()

    def generate_ai_cover(self) -> None:
        references = [item for key, item in self.cover_templates.items() if not key.startswith("ai")]
        references = references or list(self.cover_templates.values())
        if not references:
            messagebox.showerror("เจนปกไม่ได้", "ไม่พบปกต้นแบบ", parent=self)
            return
        reference = random.choice(references)
        self.cover_ai_button.configure(state="disabled")
        self.cover_ai_status_var.set("กำลังให้ AI วาดปกใหม่… (ประมาณ 1–2 นาที)")

        def worker() -> None:
            work = Path(tempfile.mkdtemp(prefix="blythe_cover_"))
            try:
                path = create_cover_template(Path(reference["path"]), work)
                with Image.open(path) as opened:
                    image = opened.convert("RGBA")
                found = detect_blank_eyes(image, (reference["left_center"], reference["right_center"]))
                if found is None:
                    # The eyes were not left blank enough to measure: reuse the reference layout.
                    found = (reference["left_center"], reference["right_center"], int(reference["eye_size"]))
                saved = save_library_cover(image, *found)
                result, error = saved, None
            except Exception as exc:
                result, error = None, str(exc)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            try:
                self.after(0, self._finish_ai_cover, result, error)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, name="blythe-ai-cover", daemon=True).start()

    def _finish_ai_cover(self, saved: Path | None, error: str | None) -> None:
        self.cover_ai_button.configure(state="normal")
        if error or saved is None:
            self.cover_ai_status_var.set("เจนปกไม่สำเร็จ")
            messagebox.showerror("เจนปกไม่สำเร็จ", error or "ไม่ทราบสาเหตุ", parent=self)
            return
        match = COVER_FILE_RE.fullmatch(saved.stem)
        new_id = f"ai{int(match.group(1)):02d}" if match else None
        self._reload_cover_templates(new_id)
        self.cover_ai_status_var.set("ได้ปกใหม่แล้ว ✓ • กำลังเซฟขึ้น GitHub")
        self._start_data_sync()

    def current_cover_template(self) -> dict[str, object] | None:
        template_id = self.cover_template_labels.get(self.cover_template_var.get())
        if template_id == "__random__":
            if self.cover_random_template_id not in self.cover_templates:
                self._pick_random_cover_template()
            template_id = self.cover_random_template_id
        return self.cover_templates.get(template_id) if template_id else None

    def _on_cover_template_changed(self, _event=None) -> None:
        if self.cover_template_var.get() == self.cover_random_label:
            self._pick_random_cover_template()
        self.show_cover_preview()

    def _pick_random_cover_template(self) -> None:
        template_ids = list(self.cover_templates)
        if not template_ids:
            self.cover_random_template_id = None
            return
        choices = [
            template_id
            for template_id in template_ids
            if template_id != self.cover_random_template_id
        ] or template_ids
        self.cover_random_template_id = random.choice(choices)

    def randomize_cover_template(self) -> None:
        self.cover_template_var.set(self.cover_random_label)
        self._pick_random_cover_template()
        self.show_cover_preview()

    def show_cover_preview(self) -> None:
        if not self.cover_selected_id:
            return
        try:
            page = render_doll_cover(
                self.prepared_assets,
                self.cover_selected_id,
                template=self.current_cover_template(),
            )
            preview = ImageOps.contain(page, (330, 330), Image.Resampling.LANCZOS)
            self.cover_preview_photo = ImageTk.PhotoImage(preview)
            self.cover_preview_label.configure(image=self.cover_preview_photo)
        except Exception:
            pass

    def cover_output_dir(self) -> Path:
        return DEFAULT_DATA_ROOT / "รูปปกลูกค้า"

    def open_cover_output_folder(self) -> None:
        folder = self.cover_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def generate_cover(self) -> None:
        if not self.cover_selected_id:
            messagebox.showwarning("ยังไม่ได้เลือก", "กรุณาเลือกหมายเลขตาก่อน")
            return
        try:
            template = self.current_cover_template()
            image = render_doll_cover(
                self.prepared_assets,
                self.cover_selected_id,
                template=template,
            )
            folder = self.cover_output_dir()
            folder.mkdir(parents=True, exist_ok=True)
            customer = sanitize_filename(self.customer_var.get())
            design_id = sanitize_filename(display_design_id(self.cover_selected_id))
            template_id = sanitize_filename(str(template.get("id"))) if template else "original"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = (
                f"cover_{customer}_t{template_id}_{design_id}"
                if customer
                else f"cover_t{template_id}_{design_id}"
            )
            output_path = folder / f"{prefix}_{stamp}.png"
            image.save(output_path, format="PNG", dpi=(DPI, DPI))
        except Exception as exc:
            messagebox.showerror("บันทึกรูปไม่สำเร็จ", str(exc))
            return
        messagebox.showinfo("บันทึกแล้ว", str(output_path))

    def reload_4x6_assets(self) -> None:
        folder = Path(self.source_4x6_var.get())
        self.six_sheets = discover_4x6_sheets(folder)
        self.six_pair_refs = OrderedDict()
        for sheet_name, path in self.six_sheets.items():
            for pair_index in range(1, 17):
                self.six_pair_refs[four_pair_key(sheet_name, pair_index)] = (path, pair_index)
        self.six_pair_refs.update(self.six_extra_refs)

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

    def add_custom_a4(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="เลือกรูปตาคัสตอมสำหรับ A4",
            filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.webp *.bmp"), ("ทุกไฟล์", "*.*")],
        )
        if not filename:
            return
        self._open_custom_a4_path(Path(filename))

    def _on_a4_file_drop(self, event) -> str:
        try:
            filenames = self.tk.splitlist(event.data)
            image_path = next((Path(value) for value in filenames if Path(value).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}), None)
        except (TypeError, ValueError, tk.TclError):
            image_path = None
        if image_path is not None:
            self._open_custom_a4_path(image_path)
        return "copy"

    def _open_custom_a4_path(self, path: Path) -> None:
        try:
            with Image.open(path) as opened:
                source = opened.convert("RGBA")
                source.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        except Exception as exc:
            messagebox.showerror("เปิดรูปคัสตอมไม่ได้", str(exc), parent=self)
            return
        kind = background_kind(source)
        if kind == "checker":
            source = remove_checker_background(source)
        self.custom_a4_image = source
        preview_source = source.copy()
        preview_source.thumbnail((512, 512), Image.Resampling.BILINEAR)
        self.custom_a4_preview_image = preview_source
        self.custom_a4_crop_source = None
        self.custom_a4_crop_preview_image = None
        self.custom_a4_crop_mode = False
        self.custom_a4_source_path = path
        self.custom_a4_zoom.set(100)
        self.custom_a4_pan_x = 0.0
        self.custom_a4_pan_y = 0.0
        notes = {
            "transparent": "พื้นหลังโปร่งใสจริง ✓ ตัดตามขอบลูกตาให้อัตโนมัติ",
            "checker": "พื้นหลังเป็นลายตารางปลอม (ไม่ใช่โปร่งใสจริง) • ลบลายตารางให้แล้ว",
        }
        self.custom_a4_crop_status.set(f"{path.name}\n{notes[kind]}" if kind in notes else path.name)
        self._update_custom_a4_crop_actions()
        self._render_custom_a4_crop()

    def _build_custom_a4_crop_panel(self, parent: tk.Misc) -> None:
        panel = tk.Frame(
            parent,
            bg=UI_SURFACE,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            padx=14,
            pady=12,
        )
        panel.pack(fill="x", padx=3, pady=(4, 12))
        panel.columnconfigure(1, weight=1)

        crop = tk.Canvas(
            panel,
            width=CUSTOM_A4_CROP_PREVIEW_PX,
            height=CUSTOM_A4_CROP_PREVIEW_PX,
            bg=UI_SURFACE,
            highlightthickness=3,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
            cursor="hand2",
        )
        crop.grid(row=0, column=0, sticky="n")
        crop.bind("<ButtonPress-1>", self._begin_custom_a4_pan)
        crop.bind("<B1-Motion>", self._move_custom_a4_pan)
        crop.bind("<ButtonRelease-1>", lambda _event: setattr(self, "custom_a4_pan_last", None))
        crop.drop_target_register(DND_FILES)
        crop.dnd_bind("<<Drop>>", self._on_a4_file_drop)
        self.custom_a4_crop_canvas = crop

        side = tk.Frame(panel, bg=UI_SURFACE)
        side.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        tk.Label(
            side, text="ครอปรูปตา", font=("Segoe UI", 12, "bold"), fg=UI_ACCENT_DARK, bg=UI_SURFACE
        ).pack(anchor="w")
        tk.Label(
            side,
            textvariable=self.custom_a4_crop_status,
            font=("Segoe UI", 9),
            fg=UI_MUTED,
            bg=UI_SURFACE,
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def step(title: str) -> tk.Frame:
            box = tk.Frame(side, bg=UI_SURFACE)
            box.pack(fill="x", pady=(4, 8))
            tk.Label(box, text=title, font=("Segoe UI", 9, "bold"), fg=UI_TEXT, bg=UI_SURFACE).pack(anchor="w", pady=(0, 4))
            return box

        choose = step("① เลือกรูป")
        ttk.Button(choose, text="เลือกรูป…", command=self.add_custom_a4).pack(fill="x")
        tk.Label(
            choose, text="หรือลากไฟล์มาวางในกรอบทางซ้าย", font=("Segoe UI", 8), fg=UI_MUTED, bg=UI_SURFACE
        ).pack(anchor="w", pady=(2, 0))

        adjust = step("② ปรับ (ถ้าต้องการ)")
        self.custom_a4_crop_toggle_button = ttk.Button(adjust, command=self._toggle_custom_a4_crop)
        self.custom_a4_crop_toggle_button.pack(fill="x")
        self.custom_a4_zoom_scale = tk.Scale(
            adjust,
            from_=50,
            to=200,
            resolution=5,
            orient="horizontal",
            variable=self.custom_a4_zoom,
            command=lambda _value: self._render_custom_a4_crop(),
            showvalue=False,
            bg=UI_SURFACE,
            fg=UI_TEXT,
            troughcolor=UI_ACCENT_SOFT,
            highlightthickness=0,
            label="ซูม (ลากรูปในกรอบเพื่อเลื่อน)",
        )
        self.custom_a4_zoom_scale.pack(fill="x", pady=(4, 0))

        send = step("③ ส่งไปใช้")
        self.custom_a4_add_a4_button = tk.Button(
            send,
            text="เพิ่มลง A4",
            command=lambda: self._apply_custom_a4_crop(persist=False),
            bg=UI_ACCENT,
            fg="white",
            activebackground=UI_ACCENT_DARK,
            activeforeground="white",
            disabledforeground="#E3F1EA",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            pady=6,
            cursor="hand2",
        )
        self.custom_a4_add_a4_button.pack(fill="x")
        row_two = tk.Frame(send, bg=UI_SURFACE)
        row_two.pack(fill="x", pady=(6, 0))
        self.custom_a4_add_4x6_button = ttk.Button(row_two, text="เพิ่มลง 4×6", command=self._custom_a4_to_4x6)
        self.custom_a4_add_4x6_button.pack(side="left", fill="x", expand=True)
        self.custom_a4_save_button = ttk.Button(
            row_two, text="บันทึกเข้าแบบที่หนึ่ง", command=lambda: self._apply_custom_a4_crop(persist=True)
        )
        self.custom_a4_save_button.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(
            send,
            text="ถ้าเปิดครอปอยู่จะใช้รูปที่ครอป ถ้าไม่ได้ครอปจะใช้รูปเต็ม",
            font=("Segoe UI", 8),
            fg=UI_MUTED,
            bg=UI_SURFACE,
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.custom_a4_crop_buttons = [
            self.custom_a4_crop_toggle_button,
            self.custom_a4_add_a4_button,
            self.custom_a4_add_4x6_button,
            self.custom_a4_save_button,
        ]
        self._update_custom_a4_crop_actions()
        if self.custom_a4_image is not None:
            self._render_custom_a4_crop()

    def _render_custom_a4_crop(self) -> None:
        canvas = self.custom_a4_crop_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        size = CUSTOM_A4_CROP_PREVIEW_PX
        # Tk canvas coordinates start under the highlight border, so offset by it
        # or the preview is shifted up-left and no longer lines up with the frame.
        inset = int(canvas.cget("highlightthickness")) + int(canvas.cget("borderwidth"))
        if self.custom_a4_image is None:
            canvas.configure(bg=UI_SURFACE, highlightbackground=UI_BORDER)
            canvas.create_text(
                inset + size // 2,
                inset + size // 2,
                text="ลากรูปมาวางในช่องนี้\n\nหรือคลิกเพื่อเลือกภาพ",
                fill=UI_MUTED,
                font=("Segoe UI", 10, "bold"),
                justify="center",
            )
            return
        try:
            if self.custom_a4_crop_mode:
                canvas.configure(bg="#9AA39E", highlightbackground="#69736D")
                eye = make_custom_a4_crop_preview(
                    self.custom_a4_crop_preview_image or self.custom_a4_image,
                    size,
                    zoom=self.custom_a4_zoom.get() / 100,
                    pan_x=self.custom_a4_pan_x,
                    pan_y=self.custom_a4_pan_y,
                )
                preview = Image.new("RGBA", eye.size, "#9AA39E")
                preview.alpha_composite(eye)
                preview.alpha_composite(make_custom_a4_crop_guide(size))
            else:
                canvas.configure(bg=UI_SURFACE, highlightbackground=UI_BORDER)
                fitted = ImageOps.contain(
                    self.custom_a4_preview_image or self.custom_a4_image,
                    (size, size),
                    Image.Resampling.BILINEAR,
                )
                preview = Image.new("RGBA", (size, size), "white")
                preview.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
            self.custom_a4_crop_photo = ImageTk.PhotoImage(preview)
            canvas.create_image(inset, inset, image=self.custom_a4_crop_photo, anchor="nw")
        except Exception as exc:
            self.custom_a4_crop_status.set(f"แสดงรูปไม่ได้: {exc}")

    def _update_custom_a4_crop_actions(self) -> None:
        has_image = self.custom_a4_image is not None
        if self.custom_a4_zoom_scale is not None:
            self.custom_a4_zoom_scale.configure(state=("normal" if has_image and self.custom_a4_crop_mode else "disabled"))
        for button in self.custom_a4_crop_buttons:
            button.configure(state=("normal" if has_image else "disabled"))
        toggle = getattr(self, "custom_a4_crop_toggle_button", None)
        if toggle is not None:
            toggle.configure(text=("✓ กำลังครอป • กดเพื่อยกเลิก" if self.custom_a4_crop_mode else "✂ ครอป / จัดตำแหน่ง"))
        add_a4 = getattr(self, "custom_a4_add_a4_button", None)
        if add_a4 is not None:
            add_a4.configure(bg=UI_ACCENT if has_image else "#A9D9BF")

    def _toggle_custom_a4_crop(self) -> None:
        if self.custom_a4_image is None:
            return
        self.custom_a4_crop_mode = not self.custom_a4_crop_mode
        if self.custom_a4_crop_mode:
            crop_source = (
                remove_outer_background(self.custom_a4_image)
                if _has_uniform_edge_background(self.custom_a4_image)
                else self.custom_a4_image
            )
            self.custom_a4_crop_source = trim_custom_a4_transparent_margin(crop_source)
            preview_source = self.custom_a4_crop_source.copy()
            preview_source.thumbnail((512, 512), Image.Resampling.BILINEAR)
            self.custom_a4_crop_preview_image = preview_source
            self.custom_a4_pan_x = self.custom_a4_pan_y = 0.0
            self.custom_a4_zoom.set(100)
            self.custom_a4_crop_status.set("โหมดครอป • ลากรูปเพื่อเลื่อน แล้วปรับซูมให้ตรงกรอบ")
        else:
            self.custom_a4_crop_source = None
            self.custom_a4_crop_preview_image = None
            self.custom_a4_crop_status.set(self.custom_a4_source_path.name if self.custom_a4_source_path else "")
            self.custom_a4_pan_last = None
        self._update_custom_a4_crop_actions()
        self._render_custom_a4_crop()

    def _begin_custom_a4_pan(self, event) -> None:
        if self.custom_a4_image is None:
            self.add_custom_a4()
            return
        if not self.custom_a4_crop_mode:
            return
        self.custom_a4_pan_last = (event.x, event.y)

    def _move_custom_a4_pan(self, event) -> None:
        if self.custom_a4_pan_last is None or self.custom_a4_crop_preview_image is None:
            return
        old_x, old_y = self.custom_a4_pan_last
        zoom = max(0.25, min(self.custom_a4_zoom.get() / 100, 2.5))
        source = self.custom_a4_crop_preview_image
        if source.width >= source.height * 1.7:
            source = source.crop((0, 0, source.width // 2, source.height))
        size = CUSTOM_A4_CROP_PREVIEW_PX
        scale = size * zoom / max(source.size)
        span_x = max(1.0, abs(source.width * scale - size) / 2)
        span_y = max(1.0, abs(source.height * scale - size) / 2)
        self.custom_a4_pan_x = max(-1.0, min(1.0, self.custom_a4_pan_x + (event.x - old_x) / span_x))
        self.custom_a4_pan_y = max(-1.0, min(1.0, self.custom_a4_pan_y + (event.y - old_y) / span_y))
        self.custom_a4_pan_last = (event.x, event.y)
        self._render_custom_a4_crop()

    def _show_custom_a4_menu(self, event, design_id: str) -> None:
        menu = tk.Menu(self, tearoff=False)
        if self.selections.get(design_id):
            menu.add_command(label="เอาออกจากรายการ A4 1 คู่", command=lambda: self.select_and_remove(design_id))
        menu.add_command(label="ส่งเข้ากล่องครอปด้านบน", command=lambda: self._send_design_to_crop(design_id))
        menu.add_command(label="ส่งไปหน้า 4×6", command=lambda: self._send_design_to_4x6(design_id))
        if not design_id.startswith("custom:"):
            menu.add_command(label="ส่งไปหน้าปก", command=lambda: self._send_design_to_cover(design_id))
        menu.add_command(label="ส่งไปหน้า AI เป็นไฟล์แนบ", command=lambda: self._send_design_to_ai(design_id))
        menu.add_separator()
        if not design_id.startswith("custom:"):
            menu.add_command(label="เปลี่ยนเบอร์", command=lambda: self._renumber_design(design_id))
            menu.add_command(label="เรียงเลขทั้งชุดใหม่ให้ต่อกัน", command=lambda: self._compact_set(design_id))
        menu.add_command(
            label=f"ลบเฉพาะรูปนี้ ({display_design_id(design_id)})",
            command=lambda: self._delete_custom_a4(design_id),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _design_source_png(self, design_id: str) -> tuple[Path, bool] | None:
        """The design's source image as a file other pages can open (PSD becomes a temporary PNG)."""
        path = self.assets.get(design_id)
        if path is None or not path.is_file():
            messagebox.showerror("ไม่พบไฟล์", f"ไม่พบไฟล์ของ {display_design_id(design_id)}", parent=self)
            return None
        if path.suffix.lower() != ".psd":
            return path, False
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            handle, name = tempfile.mkstemp(prefix="blythe_design_", suffix=".png")
            os.close(handle)
            image.save(name, format="PNG")
            return Path(name), True
        except Exception as exc:
            messagebox.showerror("เปิดไฟล์ไม่ได้", str(exc), parent=self)
            return None

    def _send_design_to_crop(self, design_id: str) -> None:
        found = self._design_source_png(design_id)
        if found is None:
            return
        self._show_page("crop")
        self._open_custom_a4_path(found[0])
        self.custom_a4_crop_status.set(f"{display_design_id(design_id)} • กด ครอป / จัดตำแหน่ง เพื่อปรับ")

    def _send_design_to_ai(self, design_id: str) -> None:
        found = self._design_source_png(design_id)
        if found is None:
            return
        self._show_page("ai_single")
        self._set_ai_reference_image(found[0], temporary=found[1])

    def _ai_result_to_crop(self) -> None:
        if self.ai_image_path is None or not self.ai_image_path.is_file():
            messagebox.showinfo("ยังไม่มีรูป", "สร้างรูปในหน้า AI ก่อน", parent=self)
            return
        self._show_page("crop")
        self._open_custom_a4_path(self.ai_image_path)

    def _ai_result_to_data(self) -> None:
        if self.ai_image_path is None or not self.ai_image_path.is_file():
            messagebox.showinfo("ยังไม่มีรูป", "สร้างรูปในหน้า AI ก่อน", parent=self)
            return
        try:
            with Image.open(self.ai_image_path) as opened:
                number = save_image_into_set(opened, Path(self.source_var.get()))
        except Exception as exc:
            messagebox.showerror("เพิ่มเข้า Data ไม่ได้", str(exc), parent=self)
            return
        old_selections = self.selections.copy()
        old_history = list(self.selection_history)
        self.reload_assets()
        self.selections = OrderedDict((key, count) for key, count in old_selections.items() if key in self.assets)
        self.selection_history = [key for key in old_history if key in self.assets]
        self.refresh_selection_status()
        self.ai_single_status_var.set(f"เพิ่มเข้า Data แบบที่หนึ่ง เบอร์ {number} แล้ว")
        self._start_data_sync()

    def _delete_custom_a4(self, design_id: str) -> None:
        if not design_id.startswith("custom:"):
            self._delete_set_design(design_id)
            return
        if not messagebox.askyesno(
            "ลบรูปคัสตอม",
            f"ลบ {display_design_id(design_id)} ทิ้งถาวร แล้วเรียงเลขคัสตอมที่เหลือใหม่ตั้งแต่ 01 ใช่ไหม?",
            parent=self,
        ):
            return
        items = OrderedDict(
            (key, (self.assets[key], tuple(self.prepared_assets[key])))
            for key in self.assets
            if key.startswith("custom:") and key.split(":", 1)[1].isdigit()
        )
        if design_id not in items:
            return
        try:
            renamed, id_map = delete_and_renumber_custom_a4(items, design_id)
        except OSError as exc:
            messagebox.showerror("ลบรูปไม่ได้", str(exc), parent=self)
            renamed, id_map = None, {}
        old_selections = self.selections.copy()
        old_history = list(self.selection_history)
        if renamed is not None:
            self.custom_a4_items = renamed
            self.custom_a4_counter = len(renamed)
        self.reload_assets()
        self.selections = OrderedDict(
            (id_map.get(key, key), count)
            for key, count in old_selections.items()
            if key != design_id and id_map.get(key, key) in self.assets
        )
        self.selection_history = [
            id_map.get(key, key)
            for key in old_history
            if key != design_id and id_map.get(key, key) in self.assets
        ]
        self.refresh_selection_status()
        if renamed is not None:
            self.custom_a4_crop_status.set(f"ลบ {display_design_id(design_id)} แล้ว • เรียงเลขใหม่ 01–{len(renamed):02d}")
            self._start_data_sync()

    def _reload_keeping_selection(self, id_map: dict[str, str] | None = None) -> None:
        id_map = id_map or {}
        old_selections = self.selections.copy()
        old_history = list(self.selection_history)
        self.reload_assets()
        self.selections = OrderedDict(
            (id_map.get(key, key), count) for key, count in old_selections.items() if id_map.get(key, key) in self.assets
        )
        self.selection_history = [id_map.get(key, key) for key in old_history if id_map.get(key, key) in self.assets]
        self.refresh_selection_status()

    def _renumber_design(self, design_id: str) -> None:
        path = self.assets.get(design_id)
        if path is None:
            return
        old_stem = path.stem
        new_stem = simpledialog.askstring(
            "เปลี่ยนเบอร์", f"เปลี่ยนเบอร์ {old_stem} เป็นเบอร์อะไร?", initialvalue=old_stem, parent=self
        )
        if not new_stem or new_stem.strip() == old_stem:
            return
        new_stem = new_stem.strip()
        group = design_id.split(":", 1)[0]
        swap = False
        if design_files(path.parent, new_stem):
            if not messagebox.askyesno(
                "เบอร์นี้มีอยู่แล้ว",
                f"มีเบอร์ {new_stem} อยู่แล้ว\n\nสลับกันไหม? (เบอร์ {new_stem} เดิมจะกลายเป็นเบอร์ {old_stem})",
                parent=self,
            ):
                return
            swap = True
        try:
            renumber_design(path.parent, old_stem, new_stem, swap=swap)
        except (OSError, ValueError) as exc:
            messagebox.showerror("เปลี่ยนเบอร์ไม่ได้", str(exc), parent=self)
            return
        id_map = {design_id: f"{group}:{new_stem}"}
        if swap:
            id_map[f"{group}:{new_stem}"] = design_id
        self._reload_keeping_selection(id_map)
        self.cache_var.set(f"เปลี่ยนเบอร์ {old_stem} → {new_stem} แล้ว" + (" (สลับกัน)" if swap else ""))
        self._start_data_sync()

    def _compact_set(self, design_id: str) -> None:
        path = self.assets.get(design_id)
        if path is None:
            return
        group = design_id.split(":", 1)[0]
        title = getattr(self, "set_titles", {}).get(int(group.removeprefix("set") or 1), "ชุดนี้")
        if not messagebox.askyesno(
            "เรียงเลขใหม่",
            f"เรียงเลขของ{title}ใหม่ให้ต่อกันตั้งแต่ 1 โดยลำดับเหมือนเดิม?\n\n"
            "เบอร์ที่ลูกค้าเคยเห็นอาจเปลี่ยน (เช่น 69 อาจกลายเป็น 63)",
            parent=self,
        ):
            return
        try:
            mapping = compact_design_numbers(path.parent)
        except OSError as exc:
            messagebox.showerror("เรียงเลขไม่ได้", str(exc), parent=self)
            return
        self._reload_keeping_selection({f"{group}:{old}": f"{group}:{new}" for old, new in mapping.items()})
        self.cache_var.set(f"เรียงเลขใหม่แล้ว • เปลี่ยน {len(mapping)} เบอร์" if mapping else "เลขต่อกันอยู่แล้ว")
        self._start_data_sync()

    def _open_trash(self, parent: tk.Toplevel) -> None:
        window = tk.Toplevel(parent)
        window.title("ถังขยะ")
        window.transient(parent)
        window.grab_set()
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="รูปที่ลบไป เลือกแล้วกดกู้คืน หรือลบถาวร", style="Muted.TLabel").pack(anchor="w")
        listbox = tk.Listbox(frame, width=58, height=12, activestyle="none")
        listbox.pack(fill="both", expand=True, pady=6)
        source = Path(self.source_var.get())
        names = {str(source): "แบบที่หนึ่ง", **{str(folder): title for _group, title, folder in self._extra_sets()}}
        entries: list[dict] = []

        def refresh() -> None:
            entries[:] = list_trash()
            listbox.delete(0, "end")
            for item in entries:
                when = item.get("deleted_at", "").replace("T", " ")
                listbox.insert("end", f"เบอร์ {item.get('stem')}  •  {names.get(item.get('folder'), item.get('folder'))}  •  ลบเมื่อ {when}")
            if not entries:
                listbox.insert("end", "ถังขยะว่าง")

        def selected() -> dict | None:
            picked = listbox.curselection()
            return entries[picked[0]] if picked and entries else None

        def restore() -> None:
            item = selected()
            if item is None:
                return
            try:
                stem = restore_from_trash(item["id"])
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("กู้คืนไม่ได้", str(exc), parent=window)
                return
            note = "" if stem == item.get("stem") else f" (เบอร์เดิมมีรูปอื่นแล้ว จึงได้เบอร์ {stem})"
            messagebox.showinfo("กู้คืนแล้ว", f"กู้คืนเบอร์ {stem} แล้ว{note}", parent=window)
            refresh()
            self._reload_keeping_selection()
            self._start_data_sync()

        def purge_one() -> None:
            item = selected()
            if item is None:
                return
            if messagebox.askyesno("ลบถาวร", f"ลบเบอร์ {item.get('stem')} ทิ้งถาวร? กู้คืนไม่ได้อีก", icon="warning", parent=window):
                purge_trash(item["id"])
                refresh()

        def purge_all() -> None:
            if entries and messagebox.askyesno("ล้างถังขยะ", "ลบทุกรูปในถังขยะทิ้งถาวร? กู้คืนไม่ได้อีก", icon="warning", parent=window):
                purge_trash()
                refresh()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="กู้คืน", command=restore).pack(side="left")
        ttk.Button(buttons, text="ลบถาวร", command=purge_one).pack(side="left", padx=6)
        ttk.Button(buttons, text="ล้างถังขยะ", command=purge_all).pack(side="left")
        ttk.Button(buttons, text="ปิด", command=window.destroy).pack(side="right")
        refresh()

    def _delete_set_design(self, design_id: str) -> None:
        path = self.assets.get(design_id)
        if path is None:
            return
        if not messagebox.askyesno(
            "ลบลายตา",
            f"ลบเฉพาะลายตาเบอร์ {display_design_id(design_id)}?\n\n"
            f"รูปจะไปอยู่ในถังขยะ {TRASH_KEEP_DAYS} วัน กู้คืนได้ที่ ตั้งค่า → ถังขยะ\n"
            "เบอร์อื่นไม่เปลี่ยน และรูปจะหายจาก GitHub ด้วย จนกว่าจะกู้คืน",
            icon="warning",
            parent=self,
        ):
            return
        try:
            # Only this number: the same design saved as .psd/.png/... but never other numbers.
            move_design_to_trash(path.parent, path.stem)
        except OSError as exc:
            messagebox.showerror("ลบไม่ได้", str(exc), parent=self)
            return
        old_selections = self.selections.copy()
        old_history = list(self.selection_history)
        self.reload_assets()
        self.selections = OrderedDict((key, count) for key, count in old_selections.items() if key in self.assets)
        self.selection_history = [key for key in old_history if key in self.assets]
        self.refresh_selection_status()
        self._start_data_sync()

    def _custom_a4_pair(self, use_crop: bool) -> tuple[Image.Image, Image.Image]:
        if use_crop:
            return make_custom_a4_pair(
                self.custom_a4_crop_source or self.custom_a4_image,
                diameter_to_pixels(DEFAULT_DIAMETER_MM),
                zoom=self.custom_a4_zoom.get() / 100,
                pan_x=self.custom_a4_pan_x,
                pan_y=self.custom_a4_pan_y,
            )
        return make_custom_a4_pair_as_is(self.custom_a4_image, diameter_to_pixels(DEFAULT_DIAMETER_MM))

    def _write_temp_pair(self, pair: tuple[Image.Image, Image.Image]) -> Path:
        """Save a pair side by side in the session temp folder (the two-up layout set files use)."""
        left, right = (flatten_to_white(eye) for eye in pair)
        sheet = Image.new("RGB", (left.width + right.width, max(left.height, right.height)), "white")
        sheet.paste(left, (0, 0))
        sheet.paste(right, (left.width, 0))
        handle, name = tempfile.mkstemp(prefix="pair_", suffix=".png", dir=self.custom_a4_temp.name)
        os.close(handle)
        sheet.save(name, format="PNG", dpi=(DPI, DPI))
        return Path(name)

    def _add_to_4x6(self, path: Path, label: str) -> None:
        """Queue a design file (two-up or single eye) on the 4x6 page."""
        key = f"data::{label}::{len(self.six_extra_refs) + 1}"
        self.six_extra_refs[key] = (path, 0)
        self.six_pair_refs[key] = (path, 0)
        self.select_4x6_and_add(key)

    def _custom_a4_to_4x6(self) -> None:
        if self.custom_a4_image is None:
            return
        try:
            path = self._write_temp_pair(self._custom_a4_pair(self.custom_a4_crop_mode))
        except Exception as exc:
            messagebox.showerror("ส่งไปหน้า 4×6 ไม่ได้", str(exc), parent=self)
            return
        self._add_to_4x6(path, "ครอป")
        self.custom_a4_crop_status.set(f"เพิ่มลงหน้า 4×6 แล้ว • ตอนนี้ {self.six_status_var.get()}")

    def _send_design_to_4x6(self, design_id: str) -> None:
        try:
            if design_id.startswith("custom:"):
                chips = self.prepared_assets[design_id]
                with Image.open(chips[0]) as left, Image.open(chips[-1]) as right:
                    path = self._write_temp_pair((left.convert("RGBA"), right.convert("RGBA")))
            else:
                path = self.assets[design_id]
                if path.suffix.lower() == ".psd":
                    with Image.open(path) as opened:
                        image = opened.convert("RGBA")
                    handle, name = tempfile.mkstemp(prefix="design_", suffix=".png", dir=self.custom_a4_temp.name)
                    os.close(handle)
                    image.save(name, format="PNG")
                    path = Path(name)
        except Exception as exc:
            messagebox.showerror("ส่งไปหน้า 4×6 ไม่ได้", str(exc), parent=self)
            return
        self._add_to_4x6(path, display_design_id(design_id))
        self.cache_var.set(f"ส่ง {display_design_id(design_id)} ไปหน้า 4×6 แล้ว • ตอนนี้ {self.six_status_var.get()}")

    def _ai_result_to_4x6(self) -> None:
        if self.ai_image_path is None or not self.ai_image_path.is_file():
            messagebox.showinfo("ยังไม่มีรูป", "สร้างรูปในหน้า AI ก่อน", parent=self)
            return
        self._add_to_4x6(self.ai_image_path, "AI")
        self.ai_single_status_var.set(f"เพิ่มลงหน้า 4×6 แล้ว • ตอนนี้ {self.six_status_var.get()}")

    def _apply_custom_a4_crop(self, persist: bool, crop: bool | None = None) -> None:
        if self.custom_a4_image is None or self.custom_a4_source_path is None:
            return
        try:
            use_crop = self.custom_a4_crop_mode if crop is None else crop
            pair = self._custom_a4_pair(use_crop)
            if persist:
                number = save_pair_into_set(pair, Path(self.source_var.get()))
                custom_id = design_key(1, number)
                old_selections = self.selections.copy()
                old_history = list(self.selection_history)
                self.reload_assets()
                self.selections = OrderedDict(
                    (key, count) for key, count in old_selections.items() if key in self.assets
                )
                self.selection_history = [key for key in old_history if key in self.assets]
                self.refresh_selection_status()
                self.select_and_add(custom_id)
                self.custom_a4_crop_status.set(f"บันทึกเป็นแบบที่หนึ่ง เบอร์ {number} แล้ว — เพิ่มลงรายการ A4 แล้ว")
                self._start_data_sync()
                return
            existing_numbers = [
                int(key.split(":", 1)[1])
                for key in self.assets
                if key.startswith("custom:") and key.split(":", 1)[1].isdigit()
            ]
            self.custom_a4_counter = max([self.custom_a4_counter, *existing_numbers], default=0) + 1
            custom_id = f"custom:{self.custom_a4_counter:03d}"
            paths = [Path(self.custom_a4_temp.name) / f"{custom_id.replace(':', '_')}_{index}.png" for index in (1, 2)]
            for eye, output in zip(pair, paths):
                eye.save(output, format="PNG", dpi=(DPI, DPI))
            old_selections = self.selections.copy()
            old_history = list(self.selection_history)
            self.custom_a4_items[custom_id] = (self.custom_a4_source_path, tuple(paths))
            self.reload_assets()
            self.selections = OrderedDict(
                (key, count) for key, count in old_selections.items() if key in self.assets
            )
            self.selection_history = [key for key in old_history if key in self.assets]
            self.refresh_selection_status()
            self.select_and_add(custom_id)
            action = "ครอปแล้ว" if use_crop else "ใช้ภาพเดิมแล้ว"
            self.custom_a4_crop_status.set(f"{action}: {display_design_id(custom_id)} (ชั่วคราว) — เพิ่มลงรายการ A4 แล้ว")
        except Exception as exc:
            messagebox.showerror("ครอปรูปไม่ได้", str(exc), parent=self)

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


def _run_update_self_test() -> bool:
    """Hooks used only by the Windows update test in CI; return True when handled."""
    if len(sys.argv) == 3 and sys.argv[1] == "--update-test":
        trace = os.environ.get("BLYTHE_UPDATE_TEST_TRACE")

        def note(message: str) -> None:
            if trace:
                with open(trace, "a", encoding="utf-8") as handle:
                    handle.write(message + "\n")

        note(f"hook start pid={os.getpid()} exe={sys.executable}")
        try:
            work_dir = Path(tempfile.mkdtemp(prefix="blythe_update_test_"))
            staged = work_dir / APP_EXECUTABLE_NAME
            shutil.copy2(sys.argv[2], staged)
            note(f"staged {staged}")
            launch_exe_updater(os.getpid(), staged, Path(sys.executable).resolve(), work_dir)
            note("updater launched")
        except Exception as exc:
            note(f"error {type(exc).__name__}: {exc}")
        return True
    marker = os.environ.get("BLYTHE_UPDATE_TEST_MARKER")
    if marker:
        Path(marker).write_text(f"{APP_VERSION}\n{Path(sys.executable).resolve()}", encoding="utf-8")
        return True
    return False


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        try:
            Path(f"{Path(sys.executable).resolve()}.old").unlink(missing_ok=True)  # left by the last update
        except OSError:
            pass
    if _run_update_self_test():
        sys.exit(0)
    try:
        purge_old_trash()  # the trash keeps deleted designs for 7 days
    except OSError:
        pass
    if ensure_release_assets():
        app = BlytheA4App()
        app.mainloop()

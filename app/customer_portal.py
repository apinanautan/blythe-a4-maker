from __future__ import annotations

import io
import base64
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageDraw, ImageOps

from blythe_ai import COLOR_PROMPTS, DESIGN_PROMPTS, STYLE_PROMPTS


PORTAL_MAX_BODY = 8 * 1024 * 1024
PORTAL_MAX_PREVIEW_BYTES = 1_800_000
PORTAL_MAX_REFERENCE_BYTES = 5 * 1024 * 1024
PORTAL_MAX_GENERATIONS = 50
PORTAL_MIN_INTERVAL_SECONDS = 4.0


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decode_reference_image(value: object) -> bytes:
    if not isinstance(value, str) or "," not in value:
        raise ValueError("รูปอ้างอิงไม่ถูกต้อง")
    header, encoded = value.split(",", 1)
    if header not in {
        "data:image/png;base64",
        "data:image/jpeg;base64",
        "data:image/webp;base64",
    }:
        raise ValueError("รองรับรูป PNG, JPG หรือ WebP เท่านั้น")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("อ่านไฟล์รูปอ้างอิงไม่สำเร็จ") from exc
    if not data or len(data) > PORTAL_MAX_REFERENCE_BYTES:
        raise ValueError("รูปอ้างอิงต้องมีขนาดไม่เกิน 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("รองรับรูป PNG, JPG หรือ WebP เท่านั้น")
            if image.width > 8192 or image.height > 8192 or image.width * image.height > 40_000_000:
                raise ValueError("ขนาดรูปใหญ่เกินไป")
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("ไฟล์รูปอ้างอิงเสียหายหรือเปิดไม่ได้") from exc
    return data


def _png_preview(image: Image.Image) -> bytes:
    """Create a small in-memory preview and never expose the source file."""
    image = image.convert("RGBA")
    if max(image.size) > 900:
        scale = 900 / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    while True:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if len(data) <= PORTAL_MAX_PREVIEW_BYTES or max(image.size) <= 420:
            return data
        image = image.resize(
            (max(1, round(image.width * 0.8)), max(1, round(image.height * 0.8))),
            Image.Resampling.LANCZOS,
        )


def _round_eye(image: Image.Image, size: int) -> Image.Image:
    chip = ImageOps.contain(image.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    canvas.alpha_composite(chip, ((size - chip.width) // 2, (size - chip.height) // 2))
    mask_large = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask_large).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    # Keep the source alpha. Replacing it with a full circle makes transparent
    # pixels around the generated eye opaque and creates a false border.
    mask = mask_large.resize((size, size), Image.Resampling.LANCZOS)
    canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), mask))
    return canvas


def _cover_template_candidates() -> list[dict[str, object]]:
    roots: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    roots.append(Path(__file__).resolve().parent)
    for root in roots:
        folder = root / "cover_assets" / "templates_gpt_blank"
        manifest = folder / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        result: list[dict[str, object]] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("base_file") or item.get("file") or "").strip()
            path = folder / filename
            if not path.is_file():
                continue
            result.append(
                {
                    "path": path,
                    "left_center": tuple(item.get("left_center") or (287, 502)),
                    "right_center": tuple(item.get("right_center") or (748, 503)),
                    "eye_size": int(item.get("eye_size") or 190),
                }
            )
        if result:
            return result
    return []


def _cover_preview(image: Image.Image) -> Image.Image:
    templates = _cover_template_candidates()
    if not templates:
        return image.convert("RGBA")
    template = random.choice(templates)
    with Image.open(Path(template["path"])) as opened:
        cover = opened.convert("RGBA").resize((1000, 1000), Image.Resampling.LANCZOS)
    size = int(template["eye_size"])
    chip = _round_eye(image, size)
    for key in ("left_center", "right_center"):
        center = tuple(int(value) for value in template[key])
        cover.alpha_composite(chip, (center[0] - size // 2, center[1] - size // 2))
    return cover


def _safe_choice(values: dict[str, str], value: object, default: str = "อัตโนมัติ") -> str:
    selected = str(value or default).strip()
    return selected if selected in values else default


def _safe_folder_name(value: object) -> str:
    name = str(value or "ลูกค้าจากลิงก์").strip()[:80]
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name).strip("._ ")
    return name or "ลูกค้าจากลิงก์"


def _options_payload() -> dict[str, object]:
    return {
        "style": list(STYLE_PROMPTS),
        "design": list(DESIGN_PROMPTS),
        "color": list(COLOR_PROMPTS),
        "defaults": {
            "style": "อัตโนมัติ",
            "design": "อัตโนมัติ",
            "primary": "อัตโนมัติ",
            "secondary": "อัตโนมัติ",
        },
    }


PORTAL_HTML = r'''<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Blythe Eye Maker</title>
  <style>
    :root { color-scheme: light; --green:#249b63; --dark:#153b2a; --mint:#e8f7ef; --line:#d7eadf; --muted:#668273; }
    * { box-sizing:border-box; }
    body { margin:0; background:#f5faf7; color:var(--dark); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
    main { width:min(100%,680px); margin:0 auto; padding:18px 14px 32px; }
    header { margin-bottom:16px; }
    h1 { margin:0; font-size:22px; letter-spacing:.1px; }
    .sub { margin:4px 0 0; color:var(--muted); font-size:13px; }
    .card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:14px; margin:12px 0; box-shadow:0 5px 18px rgba(24,76,49,.05); }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    label { display:block; font-weight:650; font-size:13px; margin-bottom:5px; }
    select, input, textarea, button { width:100%; font:inherit; border-radius:10px; }
    select, input, textarea { border:1px solid #cfe3d7; background:#fff; color:var(--dark); padding:10px; }
    textarea { min-height:78px; resize:vertical; }
    .actions { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }
    button { border:0; padding:12px 10px; font-weight:750; cursor:pointer; }
    #random { background:var(--mint); color:var(--dark); border:1px solid var(--line); }
    #generate { background:var(--green); color:#fff; }
    #save { background:#176b48; color:#fff; margin-top:10px; }
    button:disabled { opacity:.55; cursor:wait; }
    .status { min-height:22px; margin-top:10px; color:var(--muted); font-size:13px; }
    .result-title { margin:0 0 8px; font-size:14px; }
    .preview { min-height:250px; display:grid; place-items:center; background:repeating-conic-gradient(#f0f3f1 0 25%,#fff 0 50%) 50%/24px 24px; border-radius:12px; overflow:hidden; }
    .preview img { display:block; width:100%; max-height:58vh; object-fit:contain; user-select:none; -webkit-user-drag:none; }
    .hint { margin:10px 2px 0; color:var(--muted); font-size:12px; }
    .reference-row { display:flex; gap:8px; align-items:center; margin-top:10px; }
    .reference-row input { min-width:0; flex:1; }
    #clear-reference { width:auto; flex:0 0 auto; background:#f2f7f4; color:var(--dark); border:1px solid var(--line); }
    #edit-latest, #apply-edit { display:none; background:#e8f7ef; color:var(--dark); border:1px solid var(--line); margin-top:9px; }
    #edit-form { margin-top:10px; }
    @media (max-width:460px) { main { padding:14px 10px 28px; } .grid { grid-template-columns:1fr; } h1 { font-size:20px; } }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Blythe Eye Maker</h1>
    <p class="sub">ออกแบบตา 1 คู่ • ส่งคำสั่งให้โปรแกรมหลักสร้างพรีวิว</p>
  </header>
  <section class="card">
    <div class="grid">
      <div><label for="style">สไตล์</label><select id="style"></select></div>
      <div><label for="design">ลายม่านตา</label><select id="design"></select></div>
      <div><label for="primary">สีหลัก</label><select id="primary"></select></div>
      <div><label for="secondary">สีรอง</label><select id="secondary"></select></div>
    </div>
    <div style="margin-top:10px"><label for="customer">ชื่อลูกค้า / เลขออเดอร์</label><input id="customer" maxlength="80" placeholder="เช่น ลูกค้า A หรือ ออเดอร์ 001"></div>
    <div style="margin-top:10px"><label for="notes">รายละเอียดเพิ่มเติม / สิ่งที่ต้องการแก้ไข</label><textarea id="notes" maxlength="500" placeholder="เช่น โทนน้ำเงินเข้ม ดูหรู หรือปรับตาดำให้ใหญ่ขึ้น"></textarea></div>
    <div style="margin-top:10px"><label for="reference">แนบรูปตัวอย่าง (ถ้าต้องการ)</label><div class="reference-row"><input id="reference" type="file" accept="image/png,image/jpeg,image/webp"><button id="clear-reference" type="button">เอาออก</button></div><div class="hint" id="reference-status">เลือกไฟล์รูป หรือคัดลอกรูปแล้ววางในหน้านี้ได้ • ไม่เกิน 5 MB</div></div>
    <div class="actions"><button id="random" type="button">สุ่มทั้งหมด</button><button id="generate" type="button">สร้างพรีวิว</button></div>
    <button id="save" type="button" disabled>บันทึกชุดนี้เข้าฝั่งร้าน</button>
    <div class="status" id="status" aria-live="polite">พร้อมออกแบบ</div>
  </section>
  <section class="card">
    <h2 class="result-title">ตัวอย่างหน้าปก</h2>
    <div class="preview" id="cover-preview"><span class="hint">พรีวิวจะแสดงตรงนี้</span></div>
    <button id="edit-latest" type="button" disabled>แก้ไขพรีวิวล่าสุดตามรายละเอียด</button>
    <div id="edit-form" style="display:none"><label for="edit-notes">พิมพ์สิ่งที่ต้องการแก้ไขรูปนี้</label><textarea id="edit-notes" maxlength="500" placeholder="เช่น ขยายตาดำขึ้นเล็กน้อย"></textarea><button id="apply-edit" type="button" disabled>ยืนยันแก้ไขรูปนี้</button></div>
    <p class="hint">ลูกค้าจะเห็นเฉพาะหน้าปกตัวอย่าง เมื่อพอใจแล้วกดบันทึกชุดนี้ ข้อมูลจะส่งเข้าโฟลเดอร์ของร้าน</p>
  </section>
</main>
<script>
  const $ = id => document.getElementById(id);
  const state = { options:null, busy:false, previewId:null, saved:false, referenceData:null };
  const MAX_REFERENCE_BYTES = 5 * 1024 * 1024;
  function fill(id, values, selected) {
    const el = $(id); el.replaceChildren();
    values.forEach(value => { const option=document.createElement('option'); option.value=value; option.textContent=value; el.appendChild(option); });
    el.value = selected && values.includes(selected) ? selected : values[0];
  }
  async function loadOptions() {
    const response = await fetch('./api/options', {cache:'no-store'});
    if (!response.ok) throw new Error('โหลดตัวเลือกไม่สำเร็จ');
    state.options = await response.json();
    fill('style', state.options.style, state.options.defaults.style);
    fill('design', state.options.design, state.options.defaults.design);
    fill('primary', state.options.color, state.options.defaults.primary);
    fill('secondary', state.options.color, state.options.defaults.secondary);
  }
  function randomize() {
    const pick = values => values[Math.floor(Math.random()*values.length)];
    $('style').value = pick(state.options.style.filter(x => x !== 'อัตโนมัติ'));
    $('design').value = pick(state.options.design.filter(x => x !== 'อัตโนมัติ'));
    $('primary').value = pick(state.options.color.filter(x => x !== 'อัตโนมัติ'));
    $('secondary').value = pick(state.options.color.filter(x => x !== 'อัตโนมัติ'));
    $('status').textContent = 'สุ่มตัวเลือกแล้ว';
  }
  async function readReference(file) {
    if (!file) return;
    state.referenceData=null;
    if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > MAX_REFERENCE_BYTES) {
      throw new Error('เลือกไฟล์ PNG, JPG หรือ WebP ขนาดไม่เกิน 5 MB');
    }
    state.referenceData = await new Promise((resolve,reject) => {
      const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result)); reader.onerror=()=>reject(new Error('อ่านไฟล์รูปไม่สำเร็จ')); reader.readAsDataURL(file);
    });
    $('reference-status').textContent='แนบแล้ว: '+file.name+' • รูปจะถูกส่งให้โปรแกรมหลักใช้เป็นภาพอ้างอิง';
  }
  async function generate(editLatest=false) {
    if (state.busy) return;
    if (editLatest && !state.previewId) return;
    state.busy = true; state.saved=false; $('generate').disabled=true; $('random').disabled=true; $('save').disabled=true; $('edit-latest').disabled=true; $('apply-edit').disabled=true; $('status').textContent='ส่งคำสั่งให้โปรแกรมกำลังสร้าง…';
    try {
      const response = await fetch('./api/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({style:$('style').value,design:$('design').value,primary:$('primary').value,secondary:$('secondary').value,notes:editLatest?$('edit-notes').value:$('notes').value,reference_image:editLatest?null:state.referenceData,edit_preview_id:editLatest?state.previewId:null})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'สร้างพรีวิวไม่สำเร็จ');
      state.previewId=null;
      $('edit-latest').style.display='none';
      $('edit-form').style.display='none';
      $('cover-preview').replaceChildren(Object.assign(document.createElement('span'),{className:'hint',textContent:'กำลังสร้างพรีวิวใหม่…'}));
      await waitForResult(result.status_url);
    } catch (error) { $('status').textContent=error.message || 'เกิดข้อผิดพลาด'; }
    finally { state.busy=false; $('generate').disabled=false; $('random').disabled=false; $('edit-latest').disabled=!state.previewId; $('apply-edit').disabled=!state.previewId; }
  }
  async function waitForResult(statusUrl) {
    for (let attempt=0; attempt<180; attempt++) {
      const response = await fetch(statusUrl+'?v='+Date.now(), {cache:'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'อ่านผลจากโปรแกรมไม่สำเร็จ');
      if (result.status === 'queued') { $('status').textContent='รับคำสั่งแล้ว รอโปรแกรมเริ่มทำงาน…'; }
      else if (result.status === 'running') { $('status').textContent='โปรแกรมกำลังให้ GPT สร้างรูป…'; }
      else if (result.status === 'ready') {
        state.previewId=result.preview_id;
        const cover = new Image(); cover.alt='ตัวอย่างบนหน้าปก'; cover.draggable=false; cover.src=result.cover_image_url+'?v='+Date.now();
        $('cover-preview').replaceChildren(cover); $('save').disabled=false; $('edit-notes').value=''; $('edit-form').style.display='none'; $('apply-edit').style.display='none'; $('edit-latest').disabled=false; $('edit-latest').style.display='block'; $('status').textContent='สร้างหน้าปกตัวอย่างแล้ว เลือกบันทึก แก้ไข หรือสร้างใหม่ได้';
        return;
      } else if (result.status === 'error') { throw new Error(result.error || 'โปรแกรมสร้างพรีวิวไม่สำเร็จ'); }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error('รอผลนานเกินไป กรุณาลองสร้างใหม่');
  }
  async function saveSelection() {
    if (!state.previewId || state.saved || state.busy) return;
    $('save').disabled=true; $('generate').disabled=true; $('random').disabled=true; $('status').textContent='กำลังบันทึกชุดที่เลือก…';
    try {
      const response = await fetch('./api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({preview_id:state.previewId,customer:$('customer').value})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'บันทึกไม่สำเร็จ');
      state.saved=true; $('status').textContent=result.message || 'รับการบันทึกแล้ว';
    } catch (error) { $('save').disabled=false; $('status').textContent=error.message || 'บันทึกไม่สำเร็จ'; }
    finally { $('generate').disabled=false; $('random').disabled=false; }
  }
  $('random').addEventListener('click', randomize); $('generate').addEventListener('click', () => generate(false)); $('save').addEventListener('click', saveSelection);
  $('edit-latest').addEventListener('click', () => { $('edit-latest').style.display='none'; $('edit-form').style.display='block'; $('edit-notes').focus(); });
  $('edit-notes').addEventListener('input', () => { const ready=!!$('edit-notes').value.trim(); $('apply-edit').style.display=ready?'block':'none'; $('apply-edit').disabled=!ready; });
  $('apply-edit').addEventListener('click', () => generate(true));
  $('reference').addEventListener('change', event => readReference(event.target.files[0]).catch(error => $('reference-status').textContent=error.message));
  $('clear-reference').addEventListener('click', () => { state.referenceData=null; $('reference').value=''; $('reference-status').textContent='เลือกไฟล์รูป หรือคัดลอกรูปแล้ววางในหน้านี้ได้ • ไม่เกิน 5 MB'; });
  document.addEventListener('paste', event => { const item=Array.from(event.clipboardData?.items||[]).find(item=>item.type.startsWith('image/')); if(item){const file=item.getAsFile(); if(file) readReference(file).catch(error=>$('reference-status').textContent=error.message);} });
  document.addEventListener('contextmenu', event => event.preventDefault());
  document.addEventListener('dragstart', event => event.preventDefault());
  loadOptions().catch(error => $('status').textContent=error.message || 'โหลดหน้าไม่สำเร็จ');
</script>
</body>
</html>'''


class CustomerPortal:
    """Temporary mobile design page backed by the desktop app."""

    def __init__(
        self,
        on_public_url: Callable[[str], None] | None = None,
        on_generate_request: Callable[[str, dict[str, object]], None] | None = None,
        save_root: Path | None = None,
        on_selection_saved: Callable[[str, Path], None] | None = None,
    ) -> None:
        self.on_public_url = on_public_url
        self.on_generate_request = on_generate_request
        self.on_selection_saved = on_selection_saved
        self.save_root = Path(save_root) if save_root else Path.cwd() / "ลูกค้าเลือกจากลิงก์"
        self.token = secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._tunnel: subprocess.Popen[str] | None = None
        self._tunnel_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._previews: dict[str, dict[str, object]] = {}
        self._jobs: dict[str, dict[str, object]] = {}
        self._active_job_id: str | None = None
        self._generation_times: deque[float] = deque(maxlen=PORTAL_MAX_GENERATIONS)
        self._last_by_ip: dict[str, float] = {}
        self.public_url: str | None = None
        self.local_url: str | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> str:
        if self._server is not None:
            return self.public_url or str(self.local_url)

        # Reopening gets a new secret, so a copied old URL stays invalid.
        self.token = secrets.token_urlsafe(24)
        self._previews.clear()
        self._jobs.clear()
        self._active_job_id = None
        self._generation_times.clear()
        self._last_by_ip.clear()
        manager = self

        class Handler(_PortalHandler):
            portal = manager

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        port = int(self._server.server_address[1])
        self.local_url = f"http://127.0.0.1:{port}/share/{self.token}/"
        self._thread = threading.Thread(target=self._server.serve_forever, name="blythe-customer-portal", daemon=True)
        self._thread.start()
        self._start_tunnel(port)
        return self.local_url

    def stop(self) -> None:
        server, tunnel = self._server, self._tunnel
        self._server = None
        self.public_url = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if tunnel is not None and tunnel.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(tunnel.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
        self._tunnel = None
        self._previews.clear()
        self._jobs.clear()
        self._active_job_id = None

    def _cloudflared_path(self) -> str | None:
        configured = os.environ.get("CLOUDFLARED_PATH", "").strip()
        candidates = [
            Path(configured) if configured else None,
            Path.home() / "AppData" / "Roaming" / "9router" / "bin" / "cloudflared.exe",
            Path(shutil.which("cloudflared") or ""),
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return str(candidate)
        return None

    def _start_tunnel(self, port: int) -> None:
        executable = self._cloudflared_path()
        if not executable:
            return
        try:
            self._tunnel = subprocess.Popen(
                [executable, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self._tunnel = None
            return
        self._tunnel_thread = threading.Thread(target=self._read_tunnel_output, name="blythe-customer-tunnel", daemon=True)
        self._tunnel_thread.start()

    def _read_tunnel_output(self) -> None:
        process = self._tunnel
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if self._server is None:
                return
            marker = "https://"
            if marker not in line or "trycloudflare.com" not in line:
                continue
            start = line.find(marker)
            end = line.find("trycloudflare.com", start) + len("trycloudflare.com")
            host = line[start:end].rstrip("/.,)")
            if host.startswith("https://"):
                self.public_url = host + f"/share/{self.token}/"
                if self.on_public_url:
                    self.on_public_url(self.public_url)
                return

    def preview_bytes(self, preview_id: str, kind: str) -> bytes | None:
        with self._lock:
            bundle = self._previews.get(preview_id)
            value = bundle.get(kind) if bundle else None
            return value if isinstance(value, bytes) else None

    def _discard_unsaved_previews(self) -> None:
        """Drop previews that the customer did not explicitly keep."""
        with self._lock:
            for preview_id, bundle in list(self._previews.items()):
                if not bundle.get("saved"):
                    self._previews.pop(preview_id, None)

    def request_generation(self, payload: dict[str, object], remote_ip: str) -> tuple[int, dict[str, object]]:
        reference_bytes: bytes | None = None
        reference_data = payload.get("reference_image")
        if reference_data:
            try:
                reference_bytes = _decode_reference_image(reference_data)
            except ValueError as exc:
                return 400, {"error": str(exc)}
        elif payload.get("edit_preview_id"):
            preview_id = str(payload.get("edit_preview_id") or "").strip()
            with self._lock:
                bundle = self._previews.get(preview_id)
                image_data = bundle.get("eye") if bundle else None
            if not isinstance(image_data, bytes):
                return 404, {"error": "พรีวิวที่จะแก้ไขหมดอายุแล้ว กรุณาสร้างใหม่"}
            reference_bytes = image_data

        now = time.monotonic()
        with self._lock:
            if self._active_job_id is not None:
                return 409, {"error": "มีคำขอสร้างรูปอยู่แล้ว กรุณารอผลหรือกดสร้างใหม่หลังผลเสร็จ"}
            if len(self._generation_times) >= PORTAL_MAX_GENERATIONS:
                return 429, {"error": "ลิงก์นี้สร้างครบจำนวนชั่วคราวแล้ว กรุณาให้เจ้าของเปิดลิงก์ใหม่"}
            last = self._last_by_ip.get(remote_ip, 0.0)
            if now - last < PORTAL_MIN_INTERVAL_SECONDS:
                return 429, {"error": "กรุณารอสักครู่แล้วลองใหม่"}
            self._last_by_ip[remote_ip] = now
            self._generation_times.append(now)
            job_id = secrets.token_urlsafe(12)
            clean_payload = {
                "style": _safe_choice(STYLE_PROMPTS, payload.get("style")),
                "design": _safe_choice(DESIGN_PROMPTS, payload.get("design")),
                "primary": _safe_choice(COLOR_PROMPTS, payload.get("primary")),
                "secondary": _safe_choice(COLOR_PROMPTS, payload.get("secondary")),
                "notes": str(payload.get("notes") or "").strip()[:500],
            }
            if reference_bytes is not None:
                clean_payload["_reference_image_bytes"] = reference_bytes
            self._jobs[job_id] = {"status": "queued"}
            self._active_job_id = job_id
        self._discard_unsaved_previews()
        if self.on_generate_request:
            self.on_generate_request(job_id, clean_payload)
        return 202, {
            "ok": True,
            "job_id": job_id,
            "status_url": f"./api/status/{job_id}",
            "message": "ส่งคำสั่งให้โปรแกรมแล้ว",
        }

    def job_status(self, job_id: str) -> tuple[int, dict[str, object]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return 404, {"error": "ไม่พบคำขอนี้หรือคำขอหมดอายุแล้ว"}
            result = {key: value for key, value in job.items() if key != "payload"}
        return 200, result

    def complete_generation(self, job_id: str, image: Image.Image, metadata: dict[str, object]) -> None:
        eye_data = _png_preview(image)
        cover_data = _png_preview(_cover_preview(image))
        preview_id = secrets.token_urlsafe(12)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            self._previews[preview_id] = {
                "eye": eye_data,
                "cover": cover_data,
                "metadata": metadata,
                "saved": False,
            }
            while len(self._previews) > 3:
                self._previews.pop(next(iter(self._previews)))
            job.update(
                {
                    "status": "ready",
                    "preview_id": preview_id,
                    "cover_image_url": f"./image/{preview_id}/cover",
                }
            )
            self._active_job_id = None

    def fail_generation(self, job_id: str, message: str = "โปรแกรมสร้างพรีวิวไม่สำเร็จ") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update({"status": "error", "error": message})
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _write_selection(
        self,
        folder: Path,
        eye_data: bytes,
        cover_data: bytes,
        customer_name: str,
        preview_id: str,
        metadata: object,
    ) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "eye.png").write_bytes(eye_data)
            (folder / "cover_preview.png").write_bytes(cover_data)
            record = {
                "customer": customer_name,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "preview_id": preview_id,
                "options": metadata if isinstance(metadata, dict) else {},
                "files": ["eye.png", "cover_preview.png"],
            }
            (folder / "selection.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if self.on_selection_saved:
                try:
                    self.on_selection_saved(customer_name, folder)
                except Exception:
                    pass
        except OSError:
            # The mobile page already received an immediate acknowledgement.
            # There is no temporary file to clean up when the write fails.
            return

    def save_selection(self, preview_id: object, customer: object) -> tuple[int, dict[str, object]]:
        key = str(preview_id or "").strip()
        with self._lock:
            bundle = self._previews.get(key)
            if not bundle:
                return 404, {"error": "พรีวิวนี้หมดอายุแล้ว กรุณาสร้างใหม่"}
            eye_data = bundle.get("eye")
            cover_data = bundle.get("cover")
            metadata = bundle.get("metadata")
            if not isinstance(eye_data, bytes) or not isinstance(cover_data, bytes):
                return 500, {"error": "ข้อมูลพรีวิวไม่ครบ กรุณาสร้างใหม่"}
            bundle["saved"] = True

        customer_name = _safe_folder_name(customer)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        folder = self.save_root / customer_name / f"เลือกจากลิงก์_{stamp}"

        threading.Thread(
            target=self._write_selection,
            args=(folder, eye_data, cover_data, customer_name, key, metadata),
            name="blythe-customer-save",
            daemon=True,
        ).start()
        return 202, {"ok": True, "message": "รับการบันทึกแล้ว กำลังเก็บรูปเข้าฝั่งร้าน"}


class _PortalHandler(BaseHTTPRequestHandler):
    portal: CustomerPortal
    server_version = "BlytheCustomerPortal/1.0"

    def log_message(self, *_args) -> None:
        return

    def _headers(self, content_type: str, length: int | None = None) -> None:
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self._headers(content_type, len(data))
        self.end_headers()
        self.wfile.write(data)

    def _authorized_path(self) -> tuple[str, str] | None:
        parsed = urlsplit(self.path)
        bits = [part for part in parsed.path.split("/") if part]
        if len(bits) < 2 or bits[0] != "share" or bits[1] != self.portal.token:
            return None
        return parsed.path, "/".join(bits[2:])

    def do_GET(self) -> None:
        authorized = self._authorized_path()
        if authorized is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        _path, rest = authorized
        if not rest:
            self._send(HTTPStatus.OK, PORTAL_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif rest == "api/options":
            self._send(HTTPStatus.OK, _json_bytes(_options_payload()), "application/json; charset=utf-8")
        elif rest.startswith("api/status/"):
            job_id = rest.removeprefix("api/status/")
            status, result = self.portal.job_status(job_id)
            self._send(status, _json_bytes(result), "application/json; charset=utf-8")
        elif rest.startswith("image/"):
            image_bits = rest.split("/")
            preview_id = image_bits[1] if len(image_bits) == 3 else ""
            kind = image_bits[2] if len(image_bits) == 3 else ""
            data = self.portal.preview_bytes(preview_id, kind)
            if data is None:
                self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            else:
                self._send(HTTPStatus.OK, data, "image/png")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        authorized = self._authorized_path()
        if authorized is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        _path, rest = authorized
        if rest not in {"api/generate", "api/save"}:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > PORTAL_MAX_BODY:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _json_bytes({"error": "ข้อมูลยาวเกินไป"}), "application/json; charset=utf-8")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("รูปแบบข้อมูลไม่ถูกต้อง")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, _json_bytes({"error": str(exc)}), "application/json; charset=utf-8")
            return
        if rest == "api/save":
            status, result = self.portal.save_selection(
                payload.get("preview_id"),
                payload.get("customer"),
            )
        else:
            status, result = self.portal.request_generation(payload, self.client_address[0])
        self._send(status, _json_bytes(result), "application/json; charset=utf-8")

// Blythe Eye Maker for iPhone. Uses the ready-made library the desktop
// pipeline publishes on the `mobile` branch, so prints match the desktop.
"use strict";

const REPO = "apinanautan/blythe-a4-maker";
const API = `https://api.github.com/repos/${REPO}`;
const params = new URLSearchParams(location.search);
const LIBRARY = (params.get("lib") || `https://raw.githubusercontent.com/${REPO}/mobile/`).replace(/\/?$/, "/");
const APP_VERSION = "__APP_VERSION__";

const $ = (id) => document.getElementById(id);
const state = {
  index: null,
  designs: new Map(), // id -> {id, label, pieces, file, set, src?}
  a4: [], // history of design ids (order of taps)
  six: [], // history of {kind:'sheet', sheet, pair} or {kind:'design', id}
  temp: 0,
  coverId: null,
  coverTemplate: "__random__",
  coverRandom: null,
  orders: loadJSON("orders", []),
  order: null,
};

// ---------- small helpers ----------
function loadJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function saveJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage full or blocked */ }
}
function toast(text, ms = 2600) {
  const box = $("toast");
  box.textContent = text;
  box.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.add("hidden"), ms);
}
const images = new Map();
function loadImage(url) {
  if (!images.has(url)) {
    images.set(url, new Promise((resolve, reject) => {
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => resolve(image);
      image.onerror = () => { images.delete(url); reject(new Error(`โหลดรูปไม่ได้: ${url}`)); };
      image.src = url;
    }));
  }
  return images.get(url);
}
function designUrl(design) { return design.src || LIBRARY + design.file; }
function canvas(width, height) {
  const element = document.createElement("canvas");
  element.width = width; element.height = height;
  return element;
}
function stamp() {
  const d = new Date(); const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}
function safeName(text) { return (text || "").trim().replace(/[<>:"/\\|?*\s]+/g, "_").replace(/^[._]+|[._]+$/g, ""); }

// ---------- PNG with 300 DPI (pHYs) so prints come out at the real size ----------
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();
function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
async function canvasToPng(element, dpi = 300) {
  const blob = await new Promise((resolve) => element.toBlob(resolve, "image/png"));
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const perMeter = Math.round(dpi / 0.0254);
  const chunk = new Uint8Array(21);
  const view = new DataView(chunk.buffer);
  view.setUint32(0, 9);
  chunk.set([0x70, 0x48, 0x59, 0x73], 4); // "pHYs"
  view.setUint32(8, perMeter); view.setUint32(12, perMeter); chunk[16] = 1;
  view.setUint32(17, crc32(chunk.subarray(4, 17)));
  const at = 33; // right after the IHDR chunk
  const out = new Uint8Array(bytes.length + chunk.length);
  out.set(bytes.subarray(0, at)); out.set(chunk, at); out.set(bytes.subarray(at), at + chunk.length);
  return new Blob([out], { type: "image/png" });
}

// ---------- share / save (native share sheet inside the iOS app) ----------
async function blobToBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
async function shareFiles(files) {
  const native = window.webkit?.messageHandlers?.share;
  if (native) {
    const payload = [];
    for (const file of files) payload.push({ name: file.name, base64: await blobToBase64(file.blob) });
    native.postMessage({ files: payload });
    return;
  }
  const shareable = files.map((f) => new File([f.blob], f.name, { type: f.blob.type }));
  if (navigator.canShare?.({ files: shareable })) {
    try { await navigator.share({ files: shareable }); return; } catch { /* cancelled */ }
  }
  for (const file of files) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(file.blob); link.download = file.name; link.click();
  }
}

// ---------- library ----------
async function loadLibrary(force = false) {
  $("status").textContent = "กำลังโหลดลายตา…";
  try {
    const response = await fetch(LIBRARY + "index.json" + (force ? `?t=${Date.now()}` : ""), { cache: force ? "reload" : "default" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.index = await response.json();
    saveJSON("library-index", state.index);
  } catch (error) {
    state.index = loadJSON("library-index", null);
    if (!state.index) { $("status").textContent = "โหลดลายตาไม่ได้ • ตรวจอินเทอร์เน็ต"; return; }
    toast("ออฟไลน์ • ใช้ลายตาที่โหลดไว้ล่าสุด");
  }
  const temps = [...state.designs.values()].filter((d) => d.temp);
  state.designs.clear();
  for (const set of state.index.sets) for (const item of set.items) state.designs.set(item.id, { ...item, set: set.key });
  for (const extra of loadJSON("local-customs", [])) if (!state.designs.has(extra.id)) state.designs.set(extra.id, extra);
  for (const temp of temps) state.designs.set(temp.id, temp);
  const count = state.index.sets.reduce((sum, set) => sum + set.items.length, 0);
  $("status").textContent = `ลายตา ${count} แบบ`;
  renderA4();
  renderSixSheets();
  renderCoverTemplates();
  updateTray();
}

// ---------- A4 page ----------
function designsBySet() {
  const groups = [];
  for (const set of state.index.sets) {
    const items = [...state.designs.values()].filter((d) => d.set === set.key);
    if (set.key === "set4") items.push(...[...state.designs.values()].filter((d) => d.temp));
    if (items.length) groups.push({ title: set.title, items });
  }
  return groups;
}
function renderA4() {
  const host = $("a4-sets");
  host.innerHTML = "";
  for (const group of designsBySet()) {
    const title = document.createElement("h3");
    title.textContent = group.title;
    const grid = document.createElement("div");
    grid.className = "designs";
    for (const design of group.items) grid.append(designTile(design));
    host.append(title, grid);
  }
  refreshA4Badges();
}
function designTile(design) {
  const tile = document.createElement("div");
  tile.className = "design";
  tile.dataset.id = design.id;
  const eye = document.createElement("div");
  eye.className = "eye";
  eye.style.backgroundImage = `url("${designUrl(design)}")`;
  eye.style.backgroundSize = `${design.pieces * 52}px 52px`;
  const label = document.createElement("div");
  label.textContent = design.label;
  tile.append(eye, label);
  onTapOrHold(tile, () => addA4(design.id), () => designMenu(design));
  return tile;
}
function onTapOrHold(element, tap, hold) {
  let timer = null; let held = false; let start = null;
  element.addEventListener("pointerdown", (event) => {
    held = false; start = [event.clientX, event.clientY];
    timer = setTimeout(() => { held = true; hold(); }, 480);
  });
  element.addEventListener("pointermove", (event) => {
    if (start && Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 10) { clearTimeout(timer); start = null; }
  });
  element.addEventListener("pointerup", () => { clearTimeout(timer); if (!held && start) tap(); start = null; });
  element.addEventListener("pointercancel", () => { clearTimeout(timer); start = null; });
  element.addEventListener("contextmenu", (event) => event.preventDefault());
}
function addA4(id) { state.a4.push(id); refreshA4Badges(); updateTray(); }
function removeA4(id) {
  const at = state.a4.lastIndexOf(id);
  if (at >= 0) state.a4.splice(at, 1);
  refreshA4Badges(); updateTray();
}
function refreshA4Badges() {
  const counts = new Map();
  for (const id of state.a4) counts.set(id, (counts.get(id) || 0) + 1);
  for (const tile of document.querySelectorAll("#a4-sets .design")) {
    const count = counts.get(tile.dataset.id) || 0;
    tile.classList.toggle("on", count > 0);
    tile.querySelector(".badge")?.remove();
    if (count) {
      const badge = document.createElement("span");
      badge.className = "badge"; badge.textContent = `×${count}`;
      tile.append(badge);
    }
  }
}
function designMenu(design) {
  const actions = [];
  if (state.a4.includes(design.id)) actions.push(["เอาออก 1 คู่", () => removeA4(design.id)]);
  actions.push(["ส่งไปหน้า 4×6", () => { state.six.push({ kind: "design", id: design.id }); updateTray(); toast(`เพิ่ม ${design.label} ลงหน้า 4×6 แล้ว`); }]);
  actions.push(["ส่งไปหน้าปก", () => { state.coverId = design.id; showPage("cover"); }]);
  actionSheet(design.label, actions);
}
function actionSheet(title, actions) {
  const body = $("sheet-body");
  body.innerHTML = "";
  const heading = document.createElement("h2");
  heading.textContent = title;
  body.append(heading);
  for (const [label, run] of actions) {
    const button = document.createElement("button");
    button.textContent = label;
    button.onclick = () => { $("sheet").classList.add("hidden"); run(); };
    body.append(button);
  }
  const cancel = document.createElement("button");
  cancel.textContent = "ยกเลิก";
  cancel.onclick = () => $("sheet").classList.add("hidden");
  body.append(cancel);
  $("sheet").classList.remove("hidden");
}

async function designChips(id) {
  const design = state.designs.get(id);
  const image = await loadImage(designUrl(design));
  const size = image.height;
  const chips = [];
  for (let i = 0; i < design.pieces; i++) {
    const chip = canvas(size, size);
    chip.getContext("2d").drawImage(image, i * size, 0, size, size, 0, 0, size, size);
    chips.push(chip);
  }
  return chips;
}

// Same layout maths as the desktop's prepare_a4_layout / render_a4_page.
async function renderA4Pages(history) {
  const L = state.index.layout.a4;
  const size = L.chip;
  const counts = new Map();
  for (const id of history) if (state.designs.has(id)) counts.set(id, (counts.get(id) || 0) + 1);
  const slots = [];
  for (const [id, count] of counts) {
    const chips = await designChips(id);
    for (let i = 0; i < count; i++) slots.push(...chips);
  }
  const contentWidth = L.columns * size + (L.columns - 1) * L.h_gap;
  const rowPitch = size + L.v_gap;
  const rows = Math.max(1, Math.floor((L.height - L.top - L.bottom + L.v_gap) / rowPitch));
  const capacity = rows * L.columns;
  const left = Math.floor((L.width - contentWidth) / 2);
  const pages = [];
  for (let start = 0; start < slots.length; start += capacity) {
    const page = canvas(L.width, L.height);
    const ctx = page.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, L.width, L.height);
    const pageSlots = slots.slice(start, start + capacity);
    pageSlots.forEach((chip, index) => {
      const row = Math.floor(index / L.columns); const col = index % L.columns;
      ctx.drawImage(chip, left + col * (size + L.h_gap), L.top + row * rowPitch, size, size);
    });
    const rowsUsed = Math.ceil(pageSlots.length / L.columns);
    const lineY = Math.min(L.height - 1, L.top + (rowsUsed - 1) * rowPitch + size + L.cut_gap);
    ctx.fillStyle = "#000"; ctx.fillRect(0, lineY, L.width, L.cut_width); // PIL draws a 2px line on rows y and y+1
    pages.push(page);
  }
  return pages;
}

// ---------- 4x6 page ----------
function renderSixSheets() {
  const select = $("six-sheet");
  select.innerHTML = "";
  state.index.sheets.forEach((sheet, index) => select.add(new Option(sheet.name, String(index))));
  renderSixPairs();
}
async function renderSixPairs() {
  const host = $("six-pairs");
  host.innerHTML = "";
  const sheet = state.index.sheets[Number($("six-sheet").value || 0)];
  if (!sheet) { host.textContent = "ยังไม่มีไฟล์ 4×6"; return; }
  const image = await loadImage(LIBRARY + sheet.file);
  const eye = image.height / 4;
  for (let pair = 1; pair <= 16; pair++) {
    const tile = document.createElement("div");
    tile.className = "pair";
    const preview = canvas(eye * 2, eye);
    const row = Math.floor((pair - 1) / 4); const col = ((pair - 1) % 4) * 2;
    preview.getContext("2d").drawImage(image, col * eye, row * eye, eye * 2, eye, 0, 0, eye * 2, eye);
    const label = document.createElement("div");
    label.textContent = `คู่ ${pair}`;
    tile.append(preview, label);
    tile.dataset.key = `${sheet.name}::${pair}`;
    tile.onclick = () => { state.six.push({ kind: "sheet", sheet: sheet.name, pair }); updateTray(); refreshSixBadges(); };
    host.append(tile);
  }
  refreshSixBadges();
}
function refreshSixBadges() {
  const counts = new Map();
  for (const ref of state.six) if (ref.kind === "sheet") counts.set(`${ref.sheet}::${ref.pair}`, (counts.get(`${ref.sheet}::${ref.pair}`) || 0) + 1);
  for (const tile of document.querySelectorAll("#six-pairs .pair")) {
    const count = counts.get(tile.dataset.key) || 0;
    tile.classList.toggle("on", count > 0);
    tile.querySelector(".badge")?.remove();
    if (count) { const badge = document.createElement("span"); badge.className = "badge"; badge.textContent = `×${count}`; tile.append(badge); }
  }
}
async function sixPairChips(ref, size) {
  if (ref.kind === "sheet") {
    const sheet = state.index.sheets.find((s) => s.name === ref.sheet);
    if (!sheet) return null;
    const image = await loadImage(LIBRARY + sheet.file);
    const eye = image.height / 4;
    const row = Math.floor((ref.pair - 1) / 4); const col = ((ref.pair - 1) % 4) * 2;
    return [0, 1].map((offset) => {
      const chip = canvas(size, size);
      chip.getContext("2d").drawImage(image, (col + offset) * eye, row * eye, eye, eye, 0, 0, size, size);
      return chip;
    });
  }
  if (!state.designs.has(ref.id)) return null;
  const chips = await designChips(ref.id);
  return [chips[0], chips[chips.length - 1]];
}
// Same placement as the desktop's render_4x6_page.
async function renderSixPages(history) {
  const L = state.index.layout.six;
  const slots = [];
  for (const ref of history) {
    const pair = await sixPairChips(ref, L.chip);
    if (pair) slots.push(...pair);
  }
  const capacity = L.x_centers.length * L.y_centers.length;
  const pages = [];
  for (let start = 0; start < slots.length; start += capacity) {
    const page = canvas(L.width, L.height);
    const ctx = page.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, L.width, L.height);
    slots.slice(start, start + capacity).forEach((chip, index) => {
      const row = Math.floor(index / L.x_centers.length); const col = index % L.x_centers.length;
      ctx.drawImage(chip, Math.round(L.x_centers[col] - L.chip / 2), Math.round(L.y_centers[row] - L.chip / 2), L.chip, L.chip);
    });
    pages.push(page);
  }
  return pages;
}

// ---------- tray (current page's selection) ----------
function updateTray() {
  const page = state.page || "a4";
  const tray = $("tray");
  tray.classList.toggle("hidden", !(page === "a4" || page === "six"));
  if (page === "six") $("tray-text").textContent = `4×6: ${state.six.length} คู่`;
  else $("tray-text").textContent = `A4: ${state.a4.length} คู่`;
}
$("tray-undo").onclick = () => {
  if (state.page === "six") state.six.pop(); else state.a4.pop();
  refreshA4Badges(); refreshSixBadges(); updateTray();
};
$("tray-clear").onclick = () => {
  if (state.page === "six") state.six = []; else state.a4 = [];
  refreshA4Badges(); refreshSixBadges(); updateTray();
};
$("tray-make").onclick = async () => {
  try {
    toast("กำลังทำไฟล์…");
    const customer = safeName($("customer").value);
    const isSix = state.page === "six";
    const pages = isSix ? await renderSixPages(state.six) : await renderA4Pages(state.a4);
    if (!pages.length) { toast("ยังไม่ได้เลือกลาย"); return; }
    const base = `${isSix ? "4x6" : "A4"}_${customer ? customer + "_" : ""}${stamp()}`;
    const files = [];
    for (const [i, page] of pages.entries()) {
      files.push({ name: `${base}${pages.length > 1 ? `_p${i + 1}` : ""}.png`, blob: await canvasToPng(page) });
    }
    await shareFiles(files);
  } catch (error) { toast(`ทำไฟล์ไม่สำเร็จ: ${error.message}`, 4000); }
};

// ---------- Eye chip (touch crop) ----------
const chip = { image: null, scale: 1, x: 0, y: 0, pointers: new Map(), pinch: null };
function chipLayout() {
  const element = $("chip-canvas");
  const side = element.width;
  const circle = Math.round(side * 0.72);
  return { side, circle, offset: (side - circle) / 2 };
}
function resizeChipCanvas() {
  const element = $("chip-canvas");
  const side = Math.round(Math.min(element.clientWidth || 340, 520) * devicePixelRatio);
  if (element.width !== side) { element.width = side; element.height = side; fitChip(); }
  drawChip();
}
function fitChip() {
  if (!chip.image) return;
  const { side, circle } = chipLayout();
  chip.scale = circle / Math.min(chip.image.width, chip.image.height);
  chip.x = side / 2; chip.y = side / 2;
  $("chip-zoom").value = 100;
  chip.baseScale = chip.scale;
}
function drawChip() {
  const element = $("chip-canvas");
  const ctx = element.getContext("2d");
  const { side, circle, offset } = chipLayout();
  ctx.fillStyle = "#9AA39E"; ctx.fillRect(0, 0, side, side);
  if (chip.image) {
    const w = chip.image.width * chip.scale; const h = chip.image.height * chip.scale;
    ctx.drawImage(chip.image, chip.x - w / 2, chip.y - h / 2, w, h);
  } else {
    ctx.fillStyle = "#fff"; ctx.font = `${Math.round(side / 22)}px -apple-system, sans-serif`; ctx.textAlign = "center";
    ctx.fillText("เลือกรูปเพื่อเริ่ม", side / 2, side / 2);
  }
  // dim outside the crop circle and outline the cut edge
  ctx.save();
  ctx.fillStyle = "rgba(25,32,28,0.62)";
  ctx.beginPath(); ctx.rect(0, 0, side, side);
  ctx.arc(side / 2, side / 2, circle / 2, 0, Math.PI * 2, true);
  ctx.fill("evenodd");
  ctx.strokeStyle = "#fff"; ctx.lineWidth = Math.max(2, side / 180);
  ctx.beginPath(); ctx.arc(side / 2, side / 2, circle / 2, 0, Math.PI * 2); ctx.stroke();
  ctx.restore();
  for (const id of ["chip-to-a4", "chip-to-six", "chip-save"]) $(id).disabled = !chip.image;
}
function chipPoint(event) {
  const rect = $("chip-canvas").getBoundingClientRect();
  return [(event.clientX - rect.left) * ($("chip-canvas").width / rect.width), (event.clientY - rect.top) * ($("chip-canvas").height / rect.height)];
}
$("chip-canvas").addEventListener("pointerdown", (event) => {
  if (!chip.image) { $("chip-file").click(); return; }
  $("chip-canvas").setPointerCapture(event.pointerId);
  chip.pointers.set(event.pointerId, chipPoint(event));
  if (chip.pointers.size === 2) {
    const [a, b] = [...chip.pointers.values()];
    chip.pinch = { distance: Math.hypot(a[0] - b[0], a[1] - b[1]), scale: chip.scale };
  }
});
$("chip-canvas").addEventListener("pointermove", (event) => {
  if (!chip.pointers.has(event.pointerId)) return;
  const previous = chip.pointers.get(event.pointerId);
  const point = chipPoint(event);
  chip.pointers.set(event.pointerId, point);
  if (chip.pointers.size === 1) {
    chip.x += point[0] - previous[0]; chip.y += point[1] - previous[1];
  } else if (chip.pointers.size === 2 && chip.pinch) {
    const [a, b] = [...chip.pointers.values()];
    chip.scale = Math.max(chip.baseScale * 0.1, Math.min(chip.baseScale * 4, chip.pinch.scale * Math.hypot(a[0] - b[0], a[1] - b[1]) / chip.pinch.distance));
    $("chip-zoom").value = Math.round(chip.scale / chip.baseScale * 100);
  }
  drawChip();
});
for (const name of ["pointerup", "pointercancel"]) {
  $("chip-canvas").addEventListener(name, (event) => { chip.pointers.delete(event.pointerId); if (chip.pointers.size < 2) chip.pinch = null; });
}
$("chip-canvas").addEventListener("wheel", (event) => {
  if (!chip.image) return;
  event.preventDefault();
  chip.scale *= Math.pow(1.1, -event.deltaY / 100);
  $("chip-zoom").value = Math.round(chip.scale / chip.baseScale * 100);
  drawChip();
}, { passive: false });
$("chip-zoom").oninput = () => { if (chip.image) { chip.scale = chip.baseScale * $("chip-zoom").value / 100; drawChip(); } };
$("chip-file").onchange = () => {
  const file = $("chip-file").files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => { chip.image = image; fitChip(); drawChip(); };
  image.onerror = () => toast("เปิดรูปนี้ไม่ได้");
  image.src = url;
  $("chip-file").value = "";
};
// The crop circle → one round chip on white, at the A4 chip size (like make_custom_a4_pair).
function chipResult() {
  const size = state.index.layout.a4.chip;
  const { side, circle, offset } = chipLayout();
  const out = canvas(size, size);
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
  ctx.save();
  ctx.beginPath(); ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2); ctx.clip();
  const k = size / circle;
  const w = chip.image.width * chip.scale * k; const h = chip.image.height * chip.scale * k;
  ctx.drawImage(chip.image, (chip.x - offset) * k - w / 2, (chip.y - offset) * k - h / 2, w, h);
  ctx.restore();
  const pair = canvas(size * 2, size);
  pair.getContext("2d").drawImage(out, 0, 0); pair.getContext("2d").drawImage(out, size, 0);
  return pair;
}
function addTempDesign(pair) {
  state.temp += 1;
  const id = `tmp:${state.temp}`;
  state.designs.set(id, { id, label: `ชั่วคราว ${state.temp}`, pieces: 2, set: "tmp", temp: true, src: pair.toDataURL("image/png") });
  renderA4();
  return id;
}
$("chip-to-a4").onclick = () => { addA4(addTempDesign(chipResult())); toast("เพิ่มลง A4 แล้ว (ชั่วคราว)"); };
$("chip-to-six").onclick = () => { state.six.push({ kind: "design", id: addTempDesign(chipResult()) }); toast("เพิ่มลงหน้า 4×6 แล้ว"); };
$("chip-save").onclick = async () => {
  const token = localStorage.getItem("token");
  if (!token) { toast("ใส่ GitHub token ในหน้าตั้งค่าก่อน", 4000); showPage("settings"); return; }
  try {
    $("chip-save").disabled = true;
    toast("กำลังบันทึกขึ้น GitHub…");
    const pair = chipResult();
    const number = await saveCustomToGitHub(pair, token);
    const id = `set4:${number}`;
    const design = { id, label: `คัส ${number}`, pieces: 2, set: "set4", src: pair.toDataURL("image/png") };
    state.designs.set(id, design);
    const locals = loadJSON("local-customs", []).filter((d) => d.id !== id);
    locals.push(design); saveJSON("local-customs", locals);
    renderA4();
    toast(`บันทึกเป็นคัสตอม เบอร์ ${number} แล้ว`);
  } catch (error) { toast(`บันทึกไม่สำเร็จ: ${error.message}`, 5000); }
  finally { $("chip-save").disabled = false; }
};

// ---------- GitHub (same data branch the desktop syncs) ----------
async function github(method, path, token, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`GitHub ${response.status}`);
  return response.status === 204 ? null : response.json();
}
async function saveCustomToGitHub(pairCanvas, token) {
  const ref = await github("GET", "/git/ref/heads/data", token);
  const head = ref.object.sha;
  const tree = await github("GET", `/git/trees/${head}?recursive=1`, token);
  const used = new Set();
  for (const item of tree.tree) {
    const match = /^custom\/(\d+)(?:\.\d+)?\.[a-z]+$/i.exec(item.path);
    if (match) used.add(Number(match[1]));
  }
  let number = 1;
  while (used.has(number)) number += 1;
  const png = await canvasToPng(pairCanvas);
  const blob = await github("POST", "/git/blobs", token, { content: await blobToBase64(png), encoding: "base64" });
  const commit = await github("GET", `/git/commits/${head}`, token);
  const newTree = await github("POST", "/git/trees", token, {
    base_tree: commit.tree.sha,
    tree: [{ path: `custom/${number}.png`, mode: "100644", type: "blob", sha: blob.sha }],
  });
  const newCommit = await github("POST", "/git/commits", token, { message: `Add custom ${number} from iPhone`, tree: newTree.sha, parents: [head] });
  await github("PATCH", "/git/refs/heads/data", token, { sha: newCommit.sha });
  // Ask GitHub to rebuild the phone library so the new custom reaches other devices.
  github("POST", "/dispatches", token, { event_type: "library-updated" }).catch(() => {});
  return number;
}

// ---------- cover ----------
function renderCoverTemplates() {
  const select = $("cover-template");
  select.innerHTML = "";
  select.add(new Option("★ สุ่มปก", "__random__"));
  for (const cover of state.index.covers) select.add(new Option(cover.label, cover.id));
  select.value = state.coverTemplate;
}
function currentCover() {
  const covers = state.index.covers;
  if (state.coverTemplate !== "__random__") return covers.find((c) => c.id === state.coverTemplate);
  if (!covers.find((c) => c.id === state.coverRandom)) state.coverRandom = covers[Math.floor(Math.random() * covers.length)]?.id;
  return covers.find((c) => c.id === state.coverRandom);
}
// Same as the desktop's render_doll_cover: template + round eyes at the template's eye spots.
async function renderCover() {
  const cover = currentCover();
  const design = state.designs.get(state.coverId);
  $("cover-eye").textContent = design ? `รูปปก • ลายตา ${design.label}` : "รูปปก • ยังไม่ได้เลือกลายตา";
  $("cover-save").disabled = !design || !cover;
  const out = $("cover-canvas");
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, 1000, 1000);
  if (!cover) return;
  ctx.drawImage(await loadImage(LIBRARY + cover.file), 0, 0, 1000, 1000);
  if (!design) return;
  const chips = await designChips(design.id);
  for (const [center, chipCanvas] of [[cover.left, chips[0]], [cover.right, chips[chips.length - 1]]]) {
    ctx.save();
    ctx.beginPath(); ctx.arc(center[0], center[1], cover.eye / 2, 0, Math.PI * 2); ctx.clip();
    ctx.drawImage(chipCanvas, center[0] - cover.eye / 2, center[1] - cover.eye / 2, cover.eye, cover.eye);
    ctx.restore();
  }
}
$("cover-template").onchange = () => { state.coverTemplate = $("cover-template").value; renderCover(); };
$("cover-random").onclick = () => { state.coverTemplate = "__random__"; $("cover-template").value = "__random__"; state.coverRandom = null; renderCover(); };
$("cover-save").onclick = async () => {
  const design = state.designs.get(state.coverId);
  const customer = safeName($("customer").value);
  const name = `cover_${customer ? customer + "_" : ""}${safeName(design?.label)}_${stamp()}.png`;
  await shareFiles([{ name, blob: await canvasToPng($("cover-canvas")) }]);
};

// ---------- orders (kept on this phone only) ----------
function renderOrders() {
  const host = $("order-list");
  host.innerHTML = "";
  for (const order of [...state.orders].reverse()) {
    const row = document.createElement("div");
    row.className = "order" + (order.id === state.order ? " on" : "");
    row.innerHTML = `<b></b><span class="muted"></span>`;
    row.children[0].textContent = order.customer;
    row.children[1].textContent = `${order.created.slice(0, 10)} • ${order.a4.length + order.six.length} คู่`;
    row.onclick = () => { state.order = order.id; $("customer").value = order.customer; renderOrders(); };
    host.append(row);
  }
  const order = state.orders.find((o) => o.id === state.order);
  $("order-detail").classList.toggle("hidden", !order);
  if (!order) return;
  $("order-title").textContent = order.customer;
  const counts = new Map();
  for (const id of order.a4) counts.set(id, (counts.get(id) || 0) + 1);
  const a4 = [...counts].map(([id, n]) => `${state.designs.get(id)?.label ?? id}${n > 1 ? "×" + n : ""}`).join(", ") || "-";
  $("order-items").textContent = `A4: ${a4}\n4×6: ${order.six.length} คู่`;
}
function saveOrders() { saveJSON("orders", state.orders); renderOrders(); }
$("order-new").onclick = () => {
  const name = prompt("ชื่อลูกค้า", $("customer").value);
  if (!name || !name.trim()) return;
  const order = { id: `${Date.now()}`, customer: name.trim(), created: new Date().toISOString(), a4: [], six: [] };
  state.orders.push(order); state.order = order.id; $("customer").value = order.customer; saveOrders();
};
function currentOrder() { return state.orders.find((o) => o.id === state.order); }
$("order-save-selection").onclick = () => {
  const order = currentOrder(); if (!order) return;
  const skipped = state.a4.filter((id) => id.startsWith("tmp:")).length + state.six.filter((r) => r.kind === "design" && r.id.startsWith("tmp:")).length;
  order.a4 = state.a4.filter((id) => !id.startsWith("tmp:"));
  order.six = state.six.filter((r) => !(r.kind === "design" && r.id.startsWith("tmp:")));
  saveOrders();
  toast(skipped ? "บันทึกแล้ว • รูปชั่วคราวเก็บไม่ได้ ให้บันทึกเป็นคัสตอมก่อน" : "บันทึกรายการลงออเดอร์แล้ว", 4000);
};
$("order-load").onclick = () => {
  const order = currentOrder(); if (!order) return;
  state.a4 = order.a4.filter((id) => state.designs.has(id));
  state.six = [...order.six];
  refreshA4Badges(); refreshSixBadges(); showPage("a4");
};
$("order-print").onclick = async () => {
  const order = currentOrder(); if (!order) return;
  try {
    toast("กำลังทำไฟล์…");
    const name = safeName(order.customer);
    const files = [];
    const a4 = await renderA4Pages(order.a4);
    for (const [i, page] of a4.entries()) files.push({ name: `A4_${name}_${stamp()}${a4.length > 1 ? `_p${i + 1}` : ""}.png`, blob: await canvasToPng(page) });
    const six = await renderSixPages(order.six);
    for (const [i, page] of six.entries()) files.push({ name: `4x6_${name}_${stamp()}${six.length > 1 ? `_p${i + 1}` : ""}.png`, blob: await canvasToPng(page) });
    if (!files.length) { toast("ออเดอร์ว่าง • ใส่รายการก่อน"); return; }
    await shareFiles(files);
  } catch (error) { toast(`ทำไฟล์ไม่สำเร็จ: ${error.message}`, 4000); }
};
$("order-delete").onclick = () => {
  const order = currentOrder(); if (!order || !confirm(`ลบออเดอร์ ${order.customer}?`)) return;
  state.orders = state.orders.filter((o) => o.id !== order.id); state.order = null; saveOrders();
};

// ---------- settings ----------
$("token").value = localStorage.getItem("token") || "";
$("token-save").onclick = () => { localStorage.setItem("token", $("token").value.trim()); toast("บันทึก token แล้ว"); };
$("library-reload").onclick = () => { images.clear(); loadLibrary(true); };
$("settings-version").textContent = `เวอร์ชัน ${APP_VERSION} • ลายตาจาก GitHub`;

// ---------- navigation ----------
function showPage(name) {
  state.page = name;
  for (const page of document.querySelectorAll(".page")) page.classList.toggle("active", page.id === `page-${name}`);
  for (const tab of document.querySelectorAll(".tabs button")) tab.classList.toggle("active", tab.dataset.page === name);
  if (name === "chip") resizeChipCanvas();
  if (name === "cover" && state.index) renderCover();
  if (name === "orders") renderOrders();
  if (name === "six") refreshSixBadges();
  updateTray();
}
for (const tab of document.querySelectorAll(".tabs button")) tab.onclick = () => showPage(tab.dataset.page);
$("six-sheet").onchange = renderSixPairs;
$("sheet").onclick = (event) => { if (event.target === $("sheet")) $("sheet").classList.add("hidden"); };
window.addEventListener("resize", () => { if (state.page === "chip") resizeChipCanvas(); });

state.page = "a4";
loadLibrary();

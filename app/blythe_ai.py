from pathlib import Path
from datetime import datetime
from http.client import HTTPConnection, HTTPException
from io import BytesIO
import base64
import json
import os
import random
import re
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageOps


STYLE_PROMPTS = {
    "อัตโนมัติ": "",
    "สมจริง": (
        "realistic human iris, natural anatomy, fine radial iris fibers, subtle limbal ring, "
        "natural color variation, photographic iris detail"
    ),
    "อนิเมะ": (
        "anime doll eye, stylized enlarged iris, clean color gradients, crisp graphic detail, "
        "bright controlled highlights"
    ),
    "การ์ตูน": (
        "cartoon doll eye, bold clean shapes, playful color blocks, simple readable iris, "
        "polished graphic illustration"
    ),
    "BJD Resin / Glass-like": (
        "handmade BJD resin eye aesthetic, artisan painted iris beneath a glossy clear resin dome, "
        "glass-like optical depth, luminous reflections, fine layered radial texture"
    ),
    "Celestial Glass Dome": (
        "premium fantasy BJD glass-dome eye, miniature celestial storybook scene embedded inside a glossy resin iris, "
        "iridescent pearl layers, luminous depth, glowing rim, delicate magical details, collectible artisan finish"
    ),
    "แฟนตาซี": (
        "fantasy custom doll eye, jewel-like iris, magical color gradients, decorative radial motifs, "
        "premium collectible doll-eye design"
    ),
    "หมอก / Smoky Mist": (
        "minimal soft-focus doll iris inspired by ink-wash and mist, near-black central pupil, "
        "soft smoky color blooming outward in a smooth diffused gradient, very little visible iris fiber detail, "
        "feathered hazy outer edge, muted desaturated pastel tones, dreamy eerie ghost-eye mood, "
        "simple clean composition with no decorative symbols or complex patterns"
    ),
}

DESIGN_PROMPTS = {
    "อัตโนมัติ": "",
    "เส้นรัศมีธรรมชาติ": "fine natural radial iris fibers radiating cleanly from the pupil",
    "Starburst": "strong starburst rays from the pupil with layered radial streaks",
    "วงแหวนซ้อน": "multiple concentric iris rings with a clear outer limbal ring",
    "กลีบดอกไม้": "petal-like radial iris pattern arranged symmetrically around the pupil",
    "Galaxy": "galaxy-inspired iris with nebula-like speckles and luminous depth",
    "อัญมณี": "faceted gemstone-inspired iris with jewel-like highlights and crystalline depth",
    "ไล่สี Halo": "smooth halo gradient from the pupil outward with a defined outer ring",
    "กระจุด / Freckles": "fine organic iris freckles and pigment speckles with controlled spacing",
    "สองสี Split": "two-tone iris color layout blended cleanly through radial fibers",
    "Metallic Shimmer": "metallic shimmer accents embedded in layered radial iris texture",
    "Celestial Storybook": (
        "a tiny dreamy celestial diorama inside the iris with soft clouds, distant stars, a crescent moon, "
        "delicate butterflies or flowers, sparkling dust, and layered glass-like depth; elegant and uncluttered"
    ),
}

COLOR_PROMPTS = {
    "อัตโนมัติ": "",
    "ดำ": "deep black",
    "น้ำตาล": "warm brown",
    "เฮเซล": "hazel brown-green",
    "เทา": "neutral gray",
    "เงิน": "silver gray",
    "ฟ้า": "light blue",
    "น้ำเงิน": "deep blue",
    "เขียว": "natural green",
    "มรกต": "emerald green",
    "ม่วง": "violet purple",
    "ชมพู": "rose pink",
    "แดง": "ruby red",
    "ทอง": "rich gold",
    "ส้ม": "amber orange",
    "ขาว": "pearl white",
    "ฟ้าพาสเทล": "soft powder pastel blue",
    "ชมพูพาสเทล": "soft blush pastel pink",
    "ม่วงลาเวนเดอร์": "soft pastel lavender",
    "เขียวมิ้นต์": "soft pastel mint green",
    "พีชพาสเทล": "soft pastel peach",
    "เหลืองครีม": "soft pastel butter yellow",
    "ฟ้าอมม่วงพาสเทล": "soft pastel periwinkle",
    "เขียวเสจพาสเทล": "soft muted pastel sage green",
    "ออโรร่า / Celestial": "pearl aurora pastel blue, lavender, pink and champagne gold",
    "พาสเทลสุ่ม": "a random soft pastel color",
}

BACKGROUND_PROMPTS = {
    "ขาว": "pure flat white background, clean hard separation around the complete circular eye design",
    "โปร่งใส": "transparent background with a clean alpha edge around the complete circular eye design",
    "เทาอ่อน": "uniform very light gray background, no texture, no shadow, easy to isolate",
    "เขียวโครมา": "uniform chroma-key green background, no texture, no shadow, easy to isolate",
}

BACKGROUND_COLORS = {
    "ขาว": (255, 255, 255),
    "เทาอ่อน": (242, 242, 242),
    "เขียวโครมา": (0, 255, 0),
}


def _auto_choice(values: dict[str, str], selected: str) -> str:
    if selected != "อัตโนมัติ":
        return selected
    choices = [value for value in values if value != "อัตโนมัติ"]
    return random.choice(choices)


def eye_prompt(
    user_prompt: str = "",
    style: str = "สมจริง",
    background: str = "โปร่งใส",
    design: str = "เส้นรัศมีธรรมชาติ",
    color_primary: str = "น้ำตาล",
    color_secondary: str = "ทอง",
) -> str:
    style = _auto_choice(STYLE_PROMPTS, style)
    design = _auto_choice(DESIGN_PROMPTS, design)
    color_primary = _auto_choice(COLOR_PROMPTS, color_primary)
    color_secondary = _auto_choice(COLOR_PROMPTS, color_secondary)
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["สมจริง"])
    background_prompt = BACKGROUND_PROMPTS["โปร่งใส"]
    design_prompt = DESIGN_PROMPTS.get(design, DESIGN_PROMPTS["เส้นรัศมีธรรมชาติ"])
    primary = COLOR_PROMPTS.get(color_primary, color_primary)
    secondary = COLOR_PROMPTS.get(color_secondary, color_secondary)
    if style == "หมอก / Smoky Mist":
        design_prompt = (
            "keep the selected motif extremely subtle, soft and blurred inside the mist; "
            "no crisp decorative lines, no hard texture, no busy detail; " + design_prompt
        )
        primary = "muted smoky " + primary
        secondary = "soft desaturated " + secondary
    is_celestial = style == "Celestial Glass Dome" or design == "Celestial Storybook"
    subject_rules = (
        "Inside the iris, allow a refined miniature celestial storybook scene with clouds, stars, moon, "
        "butterflies or flowers, while keeping everything contained within the circular eye. "
        if is_celestial
        else "No props, no scene, no objects outside the iris. "
    )
    prompt = (
        "Create one square 1:1 Blythe doll eye-chip design. "
        "Single circular iris artwork only, front-facing, perfectly centered and symmetrical, "
        "full outer circle visible with generous clean margin on every side, no cropping, no perspective, "
        "no eyelids, no sclera eyeball, no human face, no text, no watermark. "
        f"{subject_rules}"
        f"Style: {style_prompt}. Iris design: {design_prompt}. "
        f"Color palette: dominant {primary}, secondary accents {secondary}. "
        f"Background: {background_prompt}. "
    )
    if user_prompt.strip():
        prompt += "Additional design request: " + user_prompt.strip()
    return prompt


def _chrome_relay_config() -> tuple[int, str]:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    settings_path = local / "Tidmunz Studio" / "snapgen_data" / "chrome_relay.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        port, token = settings["port"], settings["token"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid port")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("invalid token")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "ไม่พบการตั้งค่าส่วนขยาย Tidmunz ChatGPT กรุณาเปิด Tidmunz Studio รุ่นที่ใช้ส่วนขยาย"
        ) from exc
    return port, token


def _chrome_request(endpoint: str, payload: dict, conversation_state: dict[str, str] | None) -> dict:
    port, token = _chrome_relay_config()
    if conversation_state and conversation_state.get("conversation_id"):
        payload = {**payload, "conversation_id": conversation_state["conversation_id"]}
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.connect()
    except OSError as exc:
        raise RuntimeError(
            "เชื่อมต่อส่วนขยาย Tidmunz ChatGPT ไม่ได้ กรุณาเปิด Tidmunz Studio และ Chrome ของโปรแกรม"
        ) from exc
    try:
        connection.sock.settimeout(1200)
        connection.request(
            "POST", f"/{token}/v1/{endpoint}", json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = response.read()
    except (OSError, HTTPException) as exc:
        raise RuntimeError(
            "การเชื่อมต่อกับส่วนขยายขาดระหว่างรอผล กรุณาตรวจแชตใน Chrome ก่อนส่งงานเดิมอีกครั้ง"
        ) from exc
    finally:
        connection.close()
    try:
        result = json.loads(data)
    except ValueError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    error = result.get("error")
    if response.status >= 300 or error:
        message = error.get("message") if isinstance(error, dict) else error
        if response.status in (403, 404) and not message:
            message = "กรุณาเปิด Tidmunz Studio รุ่นที่ใช้ส่วนขยาย แล้วลองอีกครั้ง"
        raise RuntimeError(f"ChatGPT ผ่านส่วนขยายไม่สำเร็จ (HTTP {response.status}) • {message or 'ส่วนขยายไม่ส่งผลกลับมา'}")
    return result


def _chrome_chat(prompt: str, conversation_state: dict[str, str] | None) -> tuple[str, dict[str, str]]:
    result = _chrome_request(
        "chat/completions", {"messages": [{"role": "user", "content": prompt}]}, conversation_state,
    )
    text = str(result.get("text") or "").strip()
    conversation_id = result.get("conversation_id")
    if not text:
        raise RuntimeError("GPT ไม่ส่งแผนชุดตากลับมา")
    if not conversation_id:
        raise RuntimeError("ส่วนขยายไม่ส่งรหัสแชตสำหรับชุด 16 คู่")
    return text, {"conversation_id": str(conversation_id)}


def _chrome_image(
    prompt: str,
    conversation_state: dict[str, str] | None = None,
    reference_image: Path | None = None,
) -> Image.Image:
    payload = {"prompt": prompt}
    endpoint = "images/generations"
    if reference_image is not None:
        payload["images"] = [base64.b64encode(Path(reference_image).read_bytes()).decode("ascii")]
        endpoint = "images/edits"
    result = _chrome_request(endpoint, payload, conversation_state)
    images = result.get("data") or []
    if not images or not images[0].get("b64_json"):
        raise RuntimeError("ส่วนขยายไม่ส่งภาพจาก ChatGPT กลับมา")
    with Image.open(BytesIO(base64.b64decode(images[0]["b64_json"]))) as opened:
        image = opened.convert("RGBA")
    if conversation_state is not None:
        conversation_id = result.get("conversation_id")
        if not conversation_id:
            raise RuntimeError("ส่วนขยายไม่ส่งรหัสแชตสำหรับสร้างภาพต่อเนื่อง")
        conversation_state["conversation_id"] = str(conversation_id)
    return image


def _json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("ไม่พบ JSON")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON ต้องเป็น object")
    return value


def _validate_collection_plan(plan: dict, requested_style: str, requested_design: str) -> dict:
    allowed_styles = {value for value in STYLE_PROMPTS if value != "อัตโนมัติ"}
    allowed_designs = {value for value in DESIGN_PROMPTS if value != "อัตโนมัติ"}
    allowed_colors = {value for value in COLOR_PROMPTS if value not in {"อัตโนมัติ", "พาสเทลสุ่ม"}}

    style = requested_style if requested_style != "อัตโนมัติ" else str(plan.get("style") or "").strip()
    design = requested_design if requested_design != "อัตโนมัติ" else str(plan.get("design") or "").strip()
    if style not in allowed_styles:
        raise ValueError("GPT เลือกสไตล์ไม่ถูกต้อง")
    if design not in allowed_designs:
        raise ValueError("GPT เลือกลายม่านตาไม่ถูกต้อง")

    raw_pairs = plan.get("pairs")
    if not isinstance(raw_pairs, list) or len(raw_pairs) != 16:
        raise ValueError("แผนต้องมี 16 คู่พอดี")

    normalized: dict[int, dict[str, object]] = {}
    for item in raw_pairs:
        if not isinstance(item, dict):
            raise ValueError("ข้อมูลคู่ตาไม่ถูกต้อง")
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError) as exc:
            raise ValueError("เลขคู่ตาไม่ถูกต้อง") from exc
        if index < 1 or index > 16 or index in normalized:
            raise ValueError("เลขคู่ตาต้องเป็น 1-16 และห้ามซ้ำ")
        primary = str(item.get("primary") or "").strip()
        secondary = str(item.get("secondary") or "").strip()
        if primary not in allowed_colors or secondary not in allowed_colors:
            raise ValueError(f"คู่ {index} ใช้ชื่อสีที่โปรแกรมไม่รองรับ")
        normalized[index] = {
            "index": index,
            "primary": primary,
            "secondary": secondary,
            "variation": str(item.get("variation") or "").strip()[:240],
        }

    concept = str(plan.get("concept") or "").strip()[:500]
    direction = str(plan.get("direction") or "").strip()[:500]
    if not concept or not direction:
        raise ValueError("แผนต้องมีคอนเซ็ปต์และแนวทางรวมของทั้งชุด")
    name = str(plan.get("collection_name") or "").strip()[:80] or f"{style} {design}"
    return {
        "collection_name": name,
        "concept": concept,
        "direction": direction,
        "style": style,
        "design": design,
        "pairs": [normalized[index] for index in range(1, 17)],
    }


def design_collection_16(
    user_prompt: str = "",
    style: str = "อัตโนมัติ",
    design: str = "อัตโนมัติ",
    color_primary: str = "อัตโนมัติ",
    color_secondary: str = "อัตโนมัติ",
    conversation_state: dict[str, str] | None = None,
) -> tuple[dict, dict[str, str]]:
    styles = ", ".join(value for value in STYLE_PROMPTS if value != "อัตโนมัติ")
    designs = ", ".join(value for value in DESIGN_PROMPTS if value != "อัตโนมัติ")
    colors = ", ".join(value for value in COLOR_PROMPTS if value not in {"อัตโนมัติ", "พาสเทลสุ่ม"})
    prompt = f"""คุณเป็นนักออกแบบคอลเลกชันตาตุ๊กตา Blythe สำหรับขายเป็นพรีเซ็ต 4x6 นิ้ว
นี่เป็นขั้นวางแผนเท่านั้น ห้ามสร้างรูปภาพตอนนี้
วางคอนเซ็ปต์รวมหนึ่งชุด แล้วออกแบบแนวทางของตา 16 คู่ภายใต้คอนเซ็ปต์เดียวกัน ให้ทั้งชุดดูกลมกลืนและขายเป็นพรีเซ็ตเดียวได้ แต่แต่ละคู่มีสีหรือ variation ต่างกันอย่างมีเหตุผล ไม่สุ่มคนละธีม

ค่าที่ผู้ใช้เลือก:
- สไตล์: {style}
- ลายม่านตา: {design}
- สีหลักที่อยากใช้เป็นแนวทาง: {color_primary}
- สีรองที่อยากใช้เป็นแนวทาง: {color_secondary}
- รายละเอียดเพิ่ม: {user_prompt or 'ไม่มี'}

กติกา:
- ถ้าสไตล์เป็น "อัตโนมัติ" ให้เลือก 1 ค่าเท่านั้นจาก: {styles}
- ถ้าลายม่านตาเป็น "อัตโนมัติ" ให้เลือก 1 ค่าเท่านั้นจาก: {designs}
- ใช้สไตล์และลายเดียวกันทั้ง 16 คู่
- primary และ secondary ของแต่ละคู่ต้องเลือกจากรายชื่อนี้เท่านั้น: {colors}
- ถ้าผู้ใช้เลือกสีไว้ ให้ใช้สีนั้นเป็นแกนของ palette แต่ยังออกแบบ 16 คู่ให้มีความหลากหลายได้
- variation เป็นคำอธิบายสั้น ๆ ไม่เกินหนึ่งประโยค เพื่อปรับน้ำหนักสี ความหม่น ความสว่าง halo หรือ texture โดยยังไม่หลุดธีม
- concept อธิบายแก่นของคอลเลกชันนี้ว่าเป็นงานแนวไหน อารมณ์อะไร และภาพรวมควรให้ความรู้สึกแบบใด
- direction อธิบายภาษาภาพรวมของทั้งชุด เช่น palette, contrast, halo, texture และจังหวะความหลากหลายของ 16 คู่
- ตอบ JSON เท่านั้น ห้าม Markdown ห้ามคำอธิบายนอก JSON

รูปแบบที่ต้องส่งกลับ:
{{"collection_name":"ชื่อชุดสั้น ๆ","concept":"คอนเซ็ปต์รวม","direction":"แนวทางภาพรวมของทั้งชุด","style":"ชื่อสไตล์","design":"ชื่อลาย","pairs":[{{"index":1,"primary":"ชื่อสี","secondary":"ชื่อสี","variation":"รายละเอียดสั้น ๆ"}}]}}
ต้องมี pairs ตั้งแต่ index 1 ถึง 16 ครบพอดี"""

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            text, conversation_state = _chrome_chat(
                prompt if attempt == 0 else prompt + "\nครั้งก่อน JSON ไม่ผ่าน validation กรุณาส่งใหม่ให้ตรง schema ทุกข้อ",
                conversation_state,
            )
            return _validate_collection_plan(_json_object(text), style, design), conversation_state
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"GPT ส่งแผนชุดตาไม่ถูกต้อง: {last_error}")


def _ensure_square(image: Image.Image, background: str) -> Image.Image:
    if image.width == image.height:
        return image.copy()
    side = max(image.width, image.height)
    if background == "โปร่งใส":
        canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
        source = image.convert("RGBA")
    else:
        canvas = Image.new("RGB", (side, side), BACKGROUND_COLORS.get(background, (255, 255, 255)))
        source = image.convert("RGB")
    canvas.paste(source, ((side - source.width) // 2, (side - source.height) // 2), source if source.mode == "RGBA" else None)
    return canvas


def _remove_edge_background(image: Image.Image) -> Image.Image:
    original = image.convert("RGB")
    work = original.copy()
    marker = (255, 0, 255)
    for point in ((0, 0), (work.width - 1, 0), (0, work.height - 1), (work.width - 1, work.height - 1)):
        ImageDraw.floodfill(work, point, marker, thresh=34)
    changed = ImageChops.difference(work, original).convert("L").point(lambda value: 255 if value else 0)
    rgba = original.convert("RGBA")
    rgba.putalpha(ImageOps.invert(changed))
    return rgba


def _crop_eye_clean(image: Image.Image, padding_ratio: float = 0.06) -> Image.Image:
    """Crop the isolated eye to a centered square with a small transparent margin."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    if bbox is None:
        return rgba

    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    side = max(width, height)
    padding = max(4, round(side * padding_ratio))
    side += padding * 2
    cx = (left + right) / 2
    cy = (top + bottom) / 2

    crop_left = round(cx - side / 2)
    crop_top = round(cy - side / 2)
    crop_right = crop_left + side
    crop_bottom = crop_top + side

    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    src_left = max(0, crop_left)
    src_top = max(0, crop_top)
    src_right = min(rgba.width, crop_right)
    src_bottom = min(rgba.height, crop_bottom)
    piece = rgba.crop((src_left, src_top, src_right, src_bottom))
    dest_x = src_left - crop_left
    dest_y = src_top - crop_top
    canvas.alpha_composite(piece, (dest_x, dest_y))
    return canvas


def _create_eye(
    user_prompt: str,
    output_dir: Path,
    style: str = "สมจริง",
    background: str = "โปร่งใส",
    design: str = "เส้นรัศมีธรรมชาติ",
    color_primary: str = "น้ำตาล",
    color_secondary: str = "ทอง",
    conversation_state: dict[str, str] | None = None,
    reference_image: Path | None = None,
    output_path: Path | None = None,
) -> tuple[Path, Image.Image]:
    if reference_image is not None:
        requested_changes = [user_prompt.strip()] if user_prompt.strip() else []
        if style != "อัตโนมัติ":
            requested_changes.append(f"Style: {STYLE_PROMPTS.get(style, style)}")
        if design != "อัตโนมัติ":
            requested_changes.append(f"Iris design: {DESIGN_PROMPTS.get(design, design)}")
        if color_primary != "อัตโนมัติ":
            requested_changes.append(f"Primary iris color: {COLOR_PROMPTS.get(color_primary, color_primary)}")
        if color_secondary != "อัตโนมัติ":
            requested_changes.append(f"Secondary iris color: {COLOR_PROMPTS.get(color_secondary, color_secondary)}")
        prompt = (
            "Edit the attached image as the visual reference. Preserve its eye design, "
            "composition, circular shape, and all details the user did not ask to change. "
            "Apply only the explicit requested changes. Keep the same eye unless a change is listed. "
            "Return one finished square 1:1 eye image with the complete circular eye visible "
            "and a transparent background. Requested changes: "
            + ("; ".join(requested_changes) if requested_changes else "none; reproduce the reference faithfully")
        )
    else:
        prompt = eye_prompt(user_prompt, style, background, design, color_primary, color_secondary)
    native_rgba = _chrome_image(prompt, conversation_state, reference_image)

    has_native_transparency = (
        background == "โปร่งใส"
        and native_rgba.getchannel("A").getextrema()[0] < 255
    )

    # Always normalize *after* GPT has returned the original image.  The
    # generator can place the circular iris slightly off-centre or leave an
    # uneven amount of transparent canvas around it.  We therefore isolate the
    # artwork first, then crop every generated eye to a centred square.  No
    # stretching is performed: _crop_eye_clean() uses the larger detected axis
    # as the square side and adds equal transparent padding around the result.
    if has_native_transparency:
        isolated = native_rgba
    else:
        isolated = _ensure_square(native_rgba, "โปร่งใส")
        isolated = _remove_edge_background(isolated)

    image = _crop_eye_clean(isolated)
    image = _ensure_square(image, "โปร่งใส")

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_path or output_dir / f"blythe_ai_eye_{uuid4().hex}.png"
    image.save(path, format="PNG")
    return path, image


def create_eye(
    user_prompt: str,
    output_dir: Path,
    style: str = "สมจริง",
    background: str = "โปร่งใส",
    design: str = "เส้นรัศมีธรรมชาติ",
    color_primary: str = "น้ำตาล",
    color_secondary: str = "ทอง",
    reference_image: Path | None = None,
    conversation_state: dict[str, str] | None = None,
) -> tuple[Path, Image.Image]:
    return _create_eye(
        user_prompt,
        output_dir,
        style,
        background,
        design,
        color_primary,
        color_secondary,
        conversation_state=conversation_state,
        reference_image=reference_image,
    )


def create_eye_collection_16(
    plan: dict,
    user_prompt: str,
    output_root: Path,
    conversation_state: dict[str, str],
    progress=None,
    on_image=None,
) -> tuple[Path, list[Path], list[Image.Image]]:
    if len(plan.get("pairs") or []) != 16:
        raise ValueError("แผนชุดตาต้องมี 16 คู่")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    preset_dir = output_root / f"Preset_{stamp}"
    preset_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    images: list[Image.Image] = []

    for item in plan["pairs"]:
        index = int(item["index"])
        if progress:
            progress(
                f"สร้างคู่ {index:02d}/16 • {item['primary']} + {item['secondary']}"
                + (f" • {item.get('variation', '')}" if item.get("variation") else "")
            )
        variation = str(item.get("variation") or "").strip()
        detail_parts = [
            (
                f"This is pair {index} of one 16-pair Blythe collection. "
                "Preserve the collection concept, visual language, palette logic, "
                "and overall theme consistently."
            ),
            f"Collection concept: {plan.get('concept', '')}",
            f"Overall direction: {plan.get('direction', '')}",
            user_prompt.strip(),
            f"Pair {index} direction: {variation}" if variation else "",
        ]
        detail_parts = [part for part in detail_parts if part and not part.endswith(": ")]
        detail = ". ".join(detail_parts)
        try:
            path, image = _create_eye(
                detail,
                preset_dir,
                style=plan["style"],
                background="โปร่งใส",
                design=plan["design"],
                color_primary=item["primary"],
                color_secondary=item["secondary"],
                conversation_state=conversation_state,
                output_path=preset_dir / f"{index:02d}.png",
            )
        except Exception as exc:
            raise RuntimeError(f"สร้างคู่ {index} ไม่สำเร็จ: {exc}") from exc
        paths.append(path)
        images.append(image)
        if on_image:
            on_image(index, path, image)

    manifest = dict(plan)
    manifest["files"] = [path.name for path in paths]
    (preset_dir / "collection.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return preset_dir, paths, images


COVER_HAIR = [
    "long wavy pastel pink hair", "short platinum blonde bob with bangs", "honey brown curls",
    "lavender twin tails", "jet black hime cut", "strawberry blonde braids", "mint green bob",
    "chestnut hair with a big ribbon", "silver white long straight hair", "copper red waves",
]
COVER_OUTFIT = [
    "a lace bonnet and frilly collar", "a knit beret and cozy sweater", "a flower crown and sundress",
    "a sailor collar dress", "a velvet headband and vintage blouse", "bunny ear hood",
    "a straw hat with daisies", "a gothic lolita headdress", "a cute raincoat hood", "a pearl tiara and tulle dress",
]
COVER_BACKGROUND = [
    "soft pastel studio background", "dreamy bokeh garden", "light cream backdrop",
    "pale blue sky with clouds", "pink floral wallpaper", "warm sunset haze",
]


def cover_prompt(rng=None) -> str:
    import random as _random

    rng = rng or _random
    return (
        "Edit the attached Blythe doll cover as a layout reference. Create a NEW, different Blythe doll "
        "portrait that keeps EXACTLY the same square 1:1 framing, head size, head position, eye positions and "
        "eye size as the reference. Change the look completely: "
        f"{rng.choice(COVER_HAIR)}, wearing {rng.choice(COVER_OUTFIT)}, {rng.choice(COVER_BACKGROUND)}. "
        "The two large eyes MUST be completely blank: plain clean pure white eyeballs with NO iris, NO pupil, "
        "NO highlights and NO color inside them, only the eyelids and lashes around them, so eyes can be placed "
        "in later. Cute, high quality, soft lighting, no text, no watermark."
    )


def create_cover_template(reference_image: Path, output_dir: Path, prompt: str | None = None) -> Path:
    """Generate a new blank-eyed doll cover from an existing cover used as the layout reference."""
    image = _chrome_image(prompt or cover_prompt(), reference_image=reference_image)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"blythe_cover_{uuid4().hex}.png"
    image.save(path, format="PNG")
    return path

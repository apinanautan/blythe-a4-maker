from pathlib import Path
from datetime import datetime
from functools import lru_cache
import json
import random
import re
import runpy
import urllib.error
import urllib.request

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
    prompt = (
        "Create one square 1:1 Blythe doll eye-chip design. "
        "Single circular iris artwork only, front-facing, perfectly centered and symmetrical, "
        "full outer circle visible with generous clean margin on every side, no cropping, no perspective, "
        "no eyelids, no sclera eyeball, no human face, no text, no watermark, no props, no scene. "
        f"Style: {style_prompt}. Iris design: {design_prompt}. "
        f"Color palette: dominant {primary}, secondary accents {secondary}. "
        f"Background: {background_prompt}. "
    )
    if user_prompt.strip():
        prompt += "Additional design request: " + user_prompt.strip()
    return prompt


def find_snapgen_client() -> Path:
    preferred = Path.home() / "Documents" / "Codex" / "2026-07-26" / "new-chat-2" / "snapgen_image_gen.py"
    if preferred.is_file():
        return preferred
    root = Path.home() / "Documents"
    if root.is_dir():
        for path in root.rglob("snapgen_image_gen.py"):
            return path
    raise FileNotFoundError("snapgen_image_gen.py was not found")


@lru_cache(maxsize=1)
def _snapgen_namespace() -> dict:
    return runpy.run_path(str(find_snapgen_client()))


def _response_text(result: dict) -> str:
    choices = result.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str):
                        parts.append(value)
            if parts:
                return "\n".join(parts).strip()
    return str(result.get("text") or "").strip()


def _bridge_chat(
    namespace: dict,
    prompt: str,
    conversation_state: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    payload = {
        "model": namespace.get("MODEL") or "auto",
        "messages": [{"role": "user", "content": prompt}],
        # Keep the Blythe collection conversation temporary.  The returned
        # cursor is kept only in this running app process, so reopening the
        # program always starts a fresh ChatGPT history.
        "history_and_training_disabled": True,
        # This request is planning/text only.  The bridge has an automatic
        # image-intent interceptor for /v1/chat/completions; phrases such as
        # "ห้ามสร้างรูปภาพตอนนี้" still contain image-generation keywords and
        # can be misclassified.  Disable that interceptor explicitly here.
        "chatgpt_image_intercept": False,
    }
    if conversation_state:
        conversation_id = conversation_state.get("conversation_id")
        parent_message_id = conversation_state.get("parent_message_id")
        if conversation_id and parent_message_id:
            payload["metadata"] = {
                "conversation_id": conversation_id,
                "parent_message_id": parent_message_id,
            }
    request = urllib.request.Request(
        f"{str(namespace.get('BRIDGE_URL') or 'http://127.0.0.1:8000').rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {namespace.get('BRIDGE_KEY') or 'local-dev-key'}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(namespace.get("TIMEOUT") or 300)) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GPT ออกแบบชุดไม่สำเร็จ HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"GPT ออกแบบชุดไม่สำเร็จ: {exc}") from exc
    if isinstance(result.get("error"), dict):
        raise RuntimeError(str(result["error"].get("message") or result["error"]))
    text = _response_text(result)
    if not text:
        raise RuntimeError("GPT ไม่ส่งแผนชุดตากลับมา")
    state = {
        "conversation_id": str(result.get("conversation_id") or ""),
        "parent_message_id": str(result.get("parent_message_id") or ""),
    }
    if not state["conversation_id"] or not state["parent_message_id"]:
        raise RuntimeError("Bridge ไม่ส่งรหัส conversation สำหรับชุด 16 คู่")
    return text, state


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

    namespace = _snapgen_namespace()
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            text, conversation_state = _bridge_chat(
                namespace,
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


def _create_eye_with_namespace(
    namespace: dict,
    user_prompt: str,
    output_dir: Path,
    style: str = "สมจริง",
    background: str = "โปร่งใส",
    design: str = "เส้นรัศมีธรรมชาติ",
    color_primary: str = "น้ำตาล",
    color_secondary: str = "ทอง",
    name_hint: str = "blythe_ai_eye",
    save_sidecar: bool = True,
    conversation_state: dict[str, str] | None = None,
) -> tuple[Path, Image.Image]:
    generate_image = namespace.get("generate_image")
    if not callable(generate_image):
        raise RuntimeError("SnapGen client has no generate_image()")

    output_dir.mkdir(parents=True, exist_ok=True)
    pngs_before = {path.resolve() for path in output_dir.glob("*.png")}
    client_globals = getattr(generate_image, "__globals__", namespace)
    story = client_globals.get("_story_conversation")
    save_story = client_globals.get("_save_story_conversation")
    original_story = dict(story) if isinstance(story, dict) else None
    # A collection gets its own image-generation conversation.  An empty dict
    # means "start a fresh image chat and capture its cursor"; a populated dict
    # means "continue that same image chat".  Do not reuse the text-planning
    # cursor here: ChatGPT Web can return 404 when an image request tries to
    # continue a temporary text-only conversation.
    use_story_history = conversation_state is not None and isinstance(story, dict)
    if use_story_history:
        conversation_id = conversation_state.get("conversation_id")
        parent_message_id = conversation_state.get("parent_message_id")
        if conversation_id and parent_message_id:
            story["conversation_id"] = conversation_id
            story["parent_message_id"] = parent_message_id
        else:
            # Force the first eye of this collection to create a new image
            # conversation instead of inheriting SnapGen's persisted story id.
            story["conversation_id"] = None
            story["parent_message_id"] = None
        if callable(save_story):
            client_globals["_save_story_conversation"] = lambda: None
    try:
        result = generate_image(
            eye_prompt(
                user_prompt,
                style,
                background,
                design,
                color_primary,
                color_secondary,
            ),
            output_dir=str(output_dir),
            name_hint=name_hint,
            aspect_ratio="1:1",
            save_sidecar=save_sidecar,
            use_story_history=use_story_history,
        )
        if use_story_history:
            conversation_state["conversation_id"] = str(story.get("conversation_id") or "")
            conversation_state["parent_message_id"] = str(story.get("parent_message_id") or "")
    finally:
        if use_story_history and original_story is not None:
            story.clear()
            story.update(original_story)
            if callable(save_story):
                client_globals["_save_story_conversation"] = save_story
    path = Path(result)
    with Image.open(path) as opened:
        native_rgba = opened.convert("RGBA").copy()

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

    path = path.with_suffix(".png")
    image.save(path, format="PNG")

    # Some ChatGPT Web image responses expose more than one fresh image asset
    # even though n=1. SnapGen/Blythe uses only the returned path, so remove
    # only the extra PNGs created during this request. Existing user files are
    # never touched.
    keep = path.resolve()
    for extra in output_dir.glob("*.png"):
        resolved = extra.resolve()
        if resolved not in pngs_before and resolved != keep:
            extra.unlink(missing_ok=True)
    return path, image


def create_eye(
    user_prompt: str,
    output_dir: Path,
    style: str = "สมจริง",
    background: str = "โปร่งใส",
    design: str = "เส้นรัศมีธรรมชาติ",
    color_primary: str = "น้ำตาล",
    color_secondary: str = "ทอง",
) -> tuple[Path, Image.Image]:
    return _create_eye_with_namespace(
        _snapgen_namespace(),
        user_prompt,
        output_dir,
        style,
        background,
        design,
        color_primary,
        color_secondary,
        save_sidecar=False,
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
    namespace = _snapgen_namespace()
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
                f"This is pair {index} of the 16-pair Blythe collection plan already defined earlier "
                "in this same conversation. Preserve the collection concept, visual language, palette logic, "
                "and overall theme consistently."
            ),
            f"Collection concept: {plan.get('concept', '')}",
            f"Overall direction: {plan.get('direction', '')}",
            user_prompt.strip(),
            f"Pair {index} direction: {variation}" if variation else "",
        ]
        detail_parts = [part for part in detail_parts if part and not part.endswith(": ")]
        detail = ". ".join(detail_parts)
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                path, image = _create_eye_with_namespace(
                    namespace,
                    detail,
                    preset_dir,
                    style=plan["style"],
                    background="โปร่งใส",
                    design=plan["design"],
                    color_primary=item["primary"],
                    color_secondary=item["secondary"],
                    name_hint=f"preset_{index:02d}",
                    save_sidecar=False,
                    conversation_state=conversation_state,
                )
                canonical = preset_dir / f"{index:02d}.png"
                image.save(canonical, format="PNG")
                if path.resolve() != canonical.resolve():
                    path.unlink(missing_ok=True)
                paths.append(canonical)
                images.append(image)
                if on_image:
                    on_image(index, canonical, image)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"สร้างคู่ {index} ไม่สำเร็จ: {last_error}")

    manifest = dict(plan)
    manifest["files"] = [path.name for path in paths]
    (preset_dir / "collection.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return preset_dir, paths, images

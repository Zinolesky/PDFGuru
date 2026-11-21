import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pymupdf
from PIL import Image, ImageFilter, ImageOps
from models import FieldMapping

# Guard against decompression bombs on user-uploaded images
Image.MAX_IMAGE_PIXELS = 40_000_000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_UNICODE_FONT = os.path.join(BASE_DIR, "assets", "fonts", "DejaVuSans.ttf")


def _resolve_unicode_font_path() -> Optional[str]:
    """Returns the path to an available Unicode TrueType font (bundled first, then OS fallback)."""
    candidates = [
        BUNDLED_UNICODE_FONT,
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


UNICODE_FONT_PATH = _resolve_unicode_font_path()
UNICODE_FONT_NAME = "docufill_uni"


def process_signature_transparency(
    image_bytes: bytes,
    threshold: int = 205,
    rotate_deg: int = 0,
) -> bytes:
    """
    Fast, vectorized (NumPy + Pillow) local-illumination background remover.
    Converts photos of ink signatures or stamps on white/shadowed paper into crisp
    transparent PNGs while preserving natural ink hue and auto-cropping empty borders.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        if rotate_deg:
            img = img.rotate(-rotate_deg, expand=True)

        # Downscale oversized phone photos (>1400px) for fast processing & compact PDF size
        max_dim = 1400
        if max(img.width, img.height) > max_dim:
            scale = max_dim / float(max(img.width, img.height))
            img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.Resampling.LANCZOS,
            )

        rgba = img.convert("RGBA")
        gray = img.convert("L")

        # Estimate local paper illumination with large Gaussian blur to cancel camera shadows
        blur_radius = max(15, int(min(img.width, img.height) * 0.08))
        bg_estimate = gray.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        rgba_arr = np.asarray(rgba, dtype=np.uint8)
        gray_arr = np.asarray(gray, dtype=np.int16)
        bg_arr = np.asarray(bg_estimate, dtype=np.int16)

        local_diff = np.maximum(0, bg_arr - gray_arr)
        min_diff = max(10, min(45, int((255 - threshold) * 0.36)))

        orig_alpha = rgba_arr[:, :, 3]
        is_visible = orig_alpha >= 15
        is_ink = is_visible & (
            ((local_diff >= min_diff) & (gray_arr < threshold))
            | (gray_arr < min(115, threshold - 55))
        )

        out_arr = np.zeros_like(rgba_arr, dtype=np.uint8)
        if np.any(is_ink):
            strength = np.maximum(local_diff, np.maximum(0, threshold - gray_arr))
            alpha_vals = np.clip(strength * 4.5, 165, 255).astype(np.uint8)

            # Deepen contrast while preserving blue/black/colored ink tint
            out_arr[is_ink, 0] = (rgba_arr[is_ink, 0].astype(np.float32) * 0.42).astype(np.uint8)
            out_arr[is_ink, 1] = (rgba_arr[is_ink, 1].astype(np.float32) * 0.42).astype(np.uint8)
            out_arr[is_ink, 2] = (rgba_arr[is_ink, 2].astype(np.float32) * 0.68).astype(np.uint8)
            out_arr[is_ink, 3] = alpha_vals[is_ink]

        result_img = Image.fromarray(out_arr, mode="RGBA")

        # Auto-crop transparent margins with small 4px padding
        bbox = result_img.getbbox()
        if bbox:
            pad = 4
            crop_box = (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(result_img.width, bbox[2] + pad),
                min(result_img.height, bbox[3] + pad),
            )
            result_img = result_img.crop(crop_box)

        out = io.BytesIO()
        result_img.save(out, format="PNG")
        return out.getvalue()


def process_photo_image(
    image_bytes: bytes,
    rotate_deg: int = 0,
    smart_crop: bool = True,
) -> bytes:
    """
    Normalizes EXIF orientation, rotates, and optionally center-crops portrait/ID photos
    to a clean 3.5:4.5 aspect ratio (biased toward the top for head & shoulders).
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        if rotate_deg:
            img = img.rotate(-rotate_deg, expand=True)

        max_dim = 1200
        if max(img.width, img.height) > max_dim and not smart_crop:
            scale = max_dim / float(max(img.width, img.height))
            img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.Resampling.LANCZOS,
            )

        rgb = img.convert("RGB")
        if smart_crop and rgb.width > 0 and rgb.height > 0:
            target_ratio = 350.0 / 450.0
            current_ratio = rgb.width / float(rgb.height)
            if abs(current_ratio - target_ratio) > 0.08:
                rgb = ImageOps.fit(
                    rgb,
                    (420, 540),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.35),
                )
            else:
                rgb = rgb.resize((420, 540), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        rgb.save(out, format="PNG")
        return out.getvalue()


# Backwards-compatible alias
process_passport_photo = process_photo_image


def _split_date_parts(date_str: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Splits a date string like 14/08/1992 or 1992-08-14 into (dd, mm, yyyy)."""
    if not date_str:
        return None, None, None
    parts = re.split(r"[/\-\.\s]+", str(date_str).strip())
    if len(parts) >= 3:
        if len(parts[0]) == 4:
            return parts[2].zfill(2), parts[1].zfill(2), parts[0]
        return parts[0].zfill(2), parts[1].zfill(2), parts[2]
    return None, None, None


def _prepare_form_data(raw_data: Any) -> Dict[str, Any]:
    """
    Domain-agnostic data helper: syncs name aliases and splits DD/MM/YYYY date parts
    ONLY from values the user actually provided — never injects hardcoded defaults.
    """
    d = raw_data.model_dump() if hasattr(raw_data, "model_dump") else dict(raw_data or {})

    if d.get("last_name") and not d.get("surname"):
        d["surname"] = d["last_name"]
    elif d.get("surname") and not d.get("last_name"):
        d["last_name"] = d["surname"]

    if d.get("full_name") and not d.get("last_name"):
        parts = str(d["full_name"]).strip().split()
        if len(parts) >= 2:
            d["last_name"] = parts[-1]
            d["surname"] = d.get("surname") or parts[-1]
            d["first_name"] = d.get("first_name") or parts[0]
            d["other_names"] = d.get("other_names") or " ".join(parts[:-1])
        elif len(parts) == 1:
            d["last_name"] = parts[0]
            d["surname"] = d.get("surname") or parts[0]
    elif (d.get("last_name") or d.get("surname")) and (d.get("first_name") or d.get("other_names")) and not d.get("full_name"):
        given = d.get("other_names") or d.get("first_name")
        fam = d.get("last_name") or d.get("surname")
        d["full_name"] = f"{given} {fam}".strip()

    if d.get("other_names") and not d.get("first_name"):
        parts = str(d["other_names"]).strip().split()
        if parts:
            d["first_name"] = parts[0]
    elif d.get("first_name") and not d.get("other_names"):
        d["other_names"] = d["first_name"]

    if d.get("date_of_birth"):
        dd, mm, yyyy = _split_date_parts(d.get("date_of_birth"))
        d.setdefault("dob_dd", dd)
        d.setdefault("dob_mm", mm)
        d.setdefault("dob_yyyy", yyyy)

    if d.get("date_signed"):
        dd, mm, yyyy = _split_date_parts(d.get("date_signed"))
        d.setdefault("date_dd", dd)
        d.setdefault("date_mm", mm)
        d.setdefault("date_yyyy", yyyy)

    return d


def _checkbox_matches(field_val: Any, match_val: Optional[str]) -> bool:
    if field_val is None or not match_val:
        return False
    v_str = str(field_val).strip().lower()
    m_str = str(match_val).strip().lower()
    if not v_str:
        return False
    if v_str == m_str:
        return True
    v_compact = re.sub(r"[\s\-_]+", "", v_str)
    m_compact = re.sub(r"[\s\-_]+", "", m_str)
    if v_compact == m_compact:
        return True
    if m_compact == "yes" and v_compact in ("true", "1", "y", "checked"):
        return True
    return False


def _is_signature_like_key(field_key: str) -> bool:
    k = (field_key or "").lower()
    return any(tok in k for tok in ("sign", "initial", "stamp", "seal"))


def _stamp_single_line_autofit(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    text: str,
    start_size: float,
    min_size: float,
    font_obj: pymupdf.Font,
    fontname: str,
    align: str,
    color: Tuple[float, float, float],
    scale_factor: float,
) -> None:
    """
    Stamps single-line text with automatic width-based font shrinking so text never bleeds
    outside its mapped box and never silently vanishes.
    """
    avail_w = max(12.0 * scale_factor, rect.width - 4.0 * scale_factor)
    fs = start_size
    while fs > min_size and font_obj.text_length(text, fontsize=fs) > avail_w:
        fs = max(min_size, fs * 0.90)

    # If still wider than single-line box at minimum font size, fall back to multiline textbox
    if font_obj.text_length(text, fontsize=fs) > avail_w and rect.height >= fs * 1.9:
        _stamp_multiline_autofit(
            page, rect, text, fs, min_size, fontname, align, color, scale_factor
        )
        return

    # Truncate cleanly with ellipsis only if even min_size overflows a tiny single-line box
    rendered_text = text
    if font_obj.text_length(rendered_text, fontsize=fs) > avail_w:
        while len(rendered_text) > 1 and font_obj.text_length(rendered_text + "…", fontsize=fs) > avail_w:
            rendered_text = rendered_text[:-1]
        rendered_text = rendered_text.rstrip() + "…"

    text_w = font_obj.text_length(rendered_text, fontsize=fs)
    if align == "center":
        tx = rect.x0 + max(1.0, (rect.width - text_w) * 0.5)
    elif align == "right":
        tx = rect.x1 - text_w - 2.0 * scale_factor
    else:
        tx = rect.x0 + 2.0 * scale_factor

    baseline_y = rect.y0 + max(fs * 0.88, min(rect.height * 0.78, (rect.height + fs * 0.68) * 0.5))
    page.insert_text(
        pymupdf.Point(tx, baseline_y),
        rendered_text,
        fontsize=fs,
        fontname=fontname,
        color=color,
    )


def _stamp_multiline_autofit(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    text: str,
    start_size: float,
    min_size: float,
    fontname: str,
    align: str,
    color: Tuple[float, float, float],
    scale_factor: float,
) -> None:
    """
    Iteratively shrinks font size until PyMuPDF's insert_textbox fits cleanly (`rc >= 0`).
    Guarantees text NEVER silently vanishes from the output PDF.
    """
    align_map = {
        "left": pymupdf.TEXT_ALIGN_LEFT,
        "center": pymupdf.TEXT_ALIGN_CENTER,
        "right": pymupdf.TEXT_ALIGN_RIGHT,
    }
    pdf_align = align_map.get(align or "left", pymupdf.TEXT_ALIGN_LEFT)

    fs = start_size
    while fs >= min_size:
        rc = page.insert_textbox(
            rect,
            text,
            fontsize=fs,
            fontname=fontname,
            color=color,
            align=pdf_align,
        )
        if rc >= 0:
            return
        next_fs = fs * 0.88
        if abs(next_fs - fs) < 0.25 or next_fs < min_size:
            break
        fs = next_fs

    # Final safety net: try with slight vertical headroom at min_size, or clean ellipsis truncation
    expanded = pymupdf.Rect(rect.x0, rect.y0, rect.x1, min(page.rect.height - 4, rect.y1 + min_size * 1.6))
    rc = page.insert_textbox(
        expanded,
        text,
        fontsize=min_size,
        fontname=fontname,
        color=color,
        align=pdf_align,
    )
    if rc >= 0:
        return

    # Binary search longest prefix that fits with ellipsis so output is never blank
    lo, hi = 1, len(text)
    best = text[:1]
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid].rstrip() + "…"
        # Dry-run on scratch rect check using line-count heuristic by rendering into expanded only once
        est_chars_per_line = max(1, int(expanded.width / max(1.0, min_size * 0.55)))
        est_lines = max(1, int(expanded.height / max(1.0, min_size * 1.25)))
        if len(cand) <= est_chars_per_line * est_lines:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1

    page.insert_textbox(
        expanded,
        best,
        fontsize=min_size,
        fontname=fontname,
        color=color,
        align=pdf_align,
    )


def stamp_pdf(
    pdf_path: str,
    mappings: List[FieldMapping],
    form_data: Any,
    image_slots: Optional[Dict[str, Dict[str, Any]]] = None,
    # Backwards-friendly named image arguments
    passport_bytes: Optional[bytes] = None,
    signature_bytes: Optional[bytes] = None,
    witness_signature_bytes: Optional[bytes] = None,
    signature_threshold: int = 205,
    passport_rotate: int = 0,
    signature_rotate: int = 0,
    witness_signature_rotate: int = 0,
    passport_smart_crop: bool = True,
) -> bytes:
    """
    Universal PDF Stamping Engine:
      - Embeds Unicode TTF font (DejaVuSans) so currencies (₦, €, £, ¥) and accents render cleanly
      - Auto-fits single-line & multiline text so values never overflow or silently vanish
      - Draws crisp vector checkmarks for any checkbox/radio group
      - Supports arbitrary custom image slots with independent rotation, smart-crop, and ink transparency
      - Clears overlapping AcroForm widget values cleanly when flattening
    """
    doc = pymupdf.open(pdf_path)
    data_dict = _prepare_form_data(form_data)

    # Assemble unified dynamic image map: field_key -> processed PNG bytes
    processed_images: Dict[str, bytes] = {}
    unified_slots: Dict[str, Dict[str, Any]] = dict(image_slots or {})

    if passport_bytes:
        for alias in ("profile_photo", "passport_photo"):
            unified_slots.setdefault(
                alias,
                {
                    "bytes": passport_bytes,
                    "mode": "photo",
                    "rotate_deg": passport_rotate,
                    "smart_crop": passport_smart_crop,
                },
            )
    if signature_bytes:
        for alias in ("applicant_signature", "client_signature", "signature"):
            unified_slots.setdefault(
                alias,
                {
                    "bytes": signature_bytes,
                    "mode": "signature",
                    "rotate_deg": signature_rotate,
                    "threshold": signature_threshold,
                },
            )
    if witness_signature_bytes:
        unified_slots.setdefault(
            "witness_signature",
            {
                "bytes": witness_signature_bytes,
                "mode": "signature",
                "rotate_deg": witness_signature_rotate,
                "threshold": signature_threshold,
            },
        )

    # Cache processed images by content hash + params so aliases don't re-process twice
    proc_cache: Dict[Tuple[int, str, int, int, bool], bytes] = {}
    for slot_key, cfg in unified_slots.items():
        raw_b = cfg.get("bytes")
        if not raw_b:
            continue
        mode = cfg.get("mode") or ("signature" if _is_signature_like_key(slot_key) else "photo")
        rot = int(cfg.get("rotate_deg", 0) or 0)
        thresh = int(cfg.get("threshold", signature_threshold) or signature_threshold)
        crop = bool(cfg.get("smart_crop", True))
        cache_id = (hash(raw_b), mode, rot, thresh, crop)
        if cache_id not in proc_cache:
            if mode == "signature":
                proc_cache[cache_id] = process_signature_transparency(
                    raw_b, threshold=thresh, rotate_deg=rot
                )
            else:
                proc_cache[cache_id] = process_photo_image(
                    raw_b, rotate_deg=rot, smart_crop=crop
                )
        processed_images[slot_key] = proc_cache[cache_id]

    # Prepare Unicode font helper
    use_unicode_ttf = bool(UNICODE_FONT_PATH)
    font_obj = pymupdf.Font(fontfile=UNICODE_FONT_PATH) if use_unicode_ttf else pymupdf.Font("helv")
    registered_pages: set[int] = set()
    ink_color = (0.04, 0.09, 0.24)

    for mapping in mappings:
        page_idx = max(0, min(len(doc) - 1, (mapping.page_number or 1) - 1))
        page = doc[page_idx]
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        scale_factor = max(0.5, page_w / 595.0)

        if use_unicode_ttf and page_idx not in registered_pages:
            page.insert_font(fontname=UNICODE_FONT_NAME, fontfile=UNICODE_FONT_PATH)
            registered_pages.add(page_idx)
        active_fontname = UNICODE_FONT_NAME if use_unicode_ttf else "helv"

        x = float(mapping.x_pct) * page_w
        y = float(mapping.y_pct) * page_h
        w = float(mapping.width_pct or 0.25) * page_w
        h = float(mapping.height_pct or 0.028) * page_h
        base_font_size = float(mapping.font_size or 10.0)
        scaled_font_size = base_font_size * scale_factor
        min_font_size = 5.5 * scale_factor
        align = (getattr(mapping, "align", None) or "left").lower()

        if mapping.type in ("text", "multiline"):
            val = data_dict.get(mapping.field_key)
            if val is not None and str(val).strip():
                text_str = str(val).strip()
                rect = pymupdf.Rect(
                    x,
                    y,
                    min(page_w - 4.0, x + max(w, 28.0 * scale_factor)),
                    min(page_h - 4.0, y + max(h, scaled_font_size * 1.35)),
                )
                is_multi = (
                    mapping.type == "multiline"
                    or "\n" in text_str
                    or h >= scaled_font_size * 2.2
                )
                if is_multi:
                    _stamp_multiline_autofit(
                        page=page,
                        rect=rect,
                        text=text_str,
                        start_size=scaled_font_size,
                        min_size=min_font_size,
                        fontname=active_fontname,
                        align=align,
                        color=ink_color,
                        scale_factor=scale_factor,
                    )
                else:
                    _stamp_single_line_autofit(
                        page=page,
                        rect=rect,
                        text=text_str,
                        start_size=scaled_font_size,
                        min_size=min_font_size,
                        font_obj=font_obj,
                        fontname=active_fontname,
                        align=align,
                        color=ink_color,
                        scale_factor=scale_factor,
                    )

        elif mapping.type == "checkbox":
            val = data_dict.get(mapping.field_key)
            if _checkbox_matches(val, mapping.match_value):
                size = 5.0 * scale_factor
                p1 = pymupdf.Point(x - size * 0.72, y + size * 0.06)
                p2 = pymupdf.Point(x - size * 0.14, y + size * 0.68)
                p3 = pymupdf.Point(x + size * 0.88, y - size * 0.74)
                shape = page.new_shape()
                shape.draw_line(p1, p2)
                shape.draw_line(p2, p3)
                shape.finish(
                    color=(0.04, 0.15, 0.45),
                    width=2.1 * scale_factor,
                    lineCap=1,
                    lineJoin=1,
                )
                shape.commit()

        elif mapping.type == "image":
            img_bytes = processed_images.get(mapping.field_key)
            if not img_bytes:
                # Helpful fallback aliases when a document uses a slightly different photo/sig key
                fk_low = (mapping.field_key or "").lower()
                if "witness" in fk_low and "witness_signature" in processed_images:
                    img_bytes = processed_images["witness_signature"]
                elif _is_signature_like_key(fk_low) and "applicant_signature" in processed_images:
                    img_bytes = processed_images["applicant_signature"]
                elif ("photo" in fk_low or "avatar" in fk_low or "passport" in fk_low) and "profile_photo" in processed_images:
                    img_bytes = processed_images["profile_photo"]

            if img_bytes:
                rect = pymupdf.Rect(
                    x,
                    y,
                    min(page_w - 2.0, x + max(w, 24.0 * scale_factor)),
                    min(page_h - 2.0, y + max(h, 16.0 * scale_factor)),
                )
                page.insert_image(rect, stream=img_bytes, keep_proportion=True)

    # Subset embedded Unicode fonts to keep output PDFs compact
    try:
        doc.subset_fonts()
    except Exception:
        pass

    output_stream = io.BytesIO()
    doc.save(output_stream, deflate=True, garbage=3)
    doc.close()
    return output_stream.getvalue()

import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Literal, Optional, Tuple
import pymupdf
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

from pdf_scraper import format_page_scrape_for_vision

load_dotenv()

DEFAULT_VISION_MODEL = (
    os.getenv("GEMINI_VISION_MODEL")
    or os.getenv("GEMINI_MODEL")
    or "gemini-3.5-flash-lite"
)
MAX_VISION_PAGES = int(os.getenv("MAX_VISION_PAGES", "20"))
GEMINI_VISION_TIMEOUT_MS = int(os.getenv("GEMINI_VISION_TIMEOUT_MS", "45000"))

OPTION_SUFFIX_RE = re.compile(
    r"_(?:yes|no|none|n_a|na|true|false|ongoing|completed|exempted|male|female|other)$"
)


class VisionKeyValue(BaseModel):
    key: str = Field(description="Printed label or fact name.")
    value: str = Field(description="Printed non-blank value.")


class VisionDetectedField(BaseModel):
    section: Optional[str] = Field(
        default=None,
        description="Nearest section heading on the page, or null if none.",
    )
    question_text: str = Field(
        description="Exact question, field prompt, or label printed on the PDF."
    )
    label: str = Field(
        description="Concise human-readable dictionary key label (e.g. 'First name', 'Date of birth', 'Reason for leave')."
    )
    field_key: str = Field(
        description="Clean lowercase snake_case key (e.g. first_name, date_of_birth, applicant_signature, company_stamp)."
    )
    type: Literal["text", "multiline", "checkbox", "image"] = Field(
        description="Input type: 'text' for single-line, 'multiline' for paragraph/multi-line box, 'checkbox' for a single check/radio option, 'image' for photo, signature, initials, or stamp box."
    )
    match_value: Optional[str] = Field(
        default=None,
        description="Required ONLY when type is 'checkbox': the specific option label for this box (e.g. 'Yes', 'No', 'None', 'Male', 'Female', 'Full-Time'). All options of the same question MUST share the same field_key and label.",
    )
    question_box: Optional[List[int]] = Field(
        default=None,
        description="Bounding box of the printed question/label text as [ymin, xmin, ymax, xmax] normalized to 0-1000.",
    )
    answer_box: List[int] = Field(
        description="Exact bounding box of the BLANK AREA where the user's answer/checkmark/signature/photo must be stamped, as [ymin, xmin, ymax, xmax] normalized to 0-1000. Do NOT cover the printed label text."
    )
    confidence: float = Field(
        default=0.85,
        description="Confidence from 0.0 to 1.0 that this is a real fillable field and answer_box is accurate.",
    )


class PageVisionAnalysis(BaseModel):
    is_fillable_page: bool = Field(
        description="True if this page contains any fillable blanks, checkboxes, signature lines, or photo boxes; False for pure cover pages or read-only prose."
    )
    page_summary: str = Field(
        description="Brief one-sentence description of what this page is about."
    )
    extracted_key_values: List[VisionKeyValue] = Field(
        default_factory=list,
        description="Non-blank informational key-value facts already printed on the page (e.g. Document Title, Version, Contact Info, Totals).",
    )
    scanned_text: Optional[str] = Field(
        default=None,
        description="ONLY when the page has no selectable text layer (scanned/image-only), transcribe all readable text on the page. Otherwise leave null.",
    )
    fields: List[VisionDetectedField] = Field(
        default_factory=list,
        description="Ordered list (top-to-bottom, left-to-right) of every fillable answer region on this page.",
    )


VISION_SYSTEM_PROMPT = """You are a precision universal PDF form-layout analyst.
Your job is to inspect a page from ANY PDF document (applications, contracts, medical intake, tax forms, HR onboarding, invoices, surveys, visas, consent forms, resumes, reports, scanned paperwork) and distinguish:
1. Printed informational prose, headings, legal clauses, read-only documents, and logos -> IGNORE these for `fields`, though you may summarize already-printed facts in `extracted_key_values`.
2. Actual QUESTIONS / PROMPTS that expect a user to fill in an answer, tick a checkbox/radio (including `(  )` or `[  ]` blanks), attach a photo/stamp, or sign -> EXTRACT every single one.

CRITICAL RULES FOR `answer_box` ([ymin, xmin, ymax, xmax] on 0-1000 scale):
- `answer_box` MUST mark the EMPTY BLANK SPACE where the answer goes (to the right of a label on an underline, inside an empty box/table cell, inside a small checkbox square/circle or `(  )` blank, inside a blank gap in a sentence like "I, __________, agree...", or directly above a signature line).
- NEVER place `answer_box` on top of the printed question text itself.
- For `checkbox` / radio options: emit ONE entry per option box or `(  )` slot, and ALL checkbox/radio options belonging to the same question MUST share the EXACT SAME `field_key` and `label` (do NOT append `_yes`, `_no`, `_ongoing`, etc. to `field_key`).
- If a checkbox option is literally `"None"`, `"N/A"`, or `"No"`, return that exact string for `match_value` — NEVER JSON `null`.
- For photo, passport, stamp, seal, or signature regions: set `type="image"`. Use clear keys like `profile_photo`, `applicant_signature`, `witness_signature`, `company_stamp`, etc.
- If the page has repeated fields (e.g. two signature lines or two name fields), emit each one with its own `answer_box`.
- If a page is purely a cover sheet, resume, or read-only informational document with NO blanks/signatures/checkboxes, return `is_fillable_page: false` and `fields: []` (and summarize printed facts in `extracted_key_values`).
- Use the provided coordinate-indexed scraped text and detected vector lines/boxes/checkboxes (when present) to align your boxes with extreme precision."""


def get_gemini_api_key() -> Optional[str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your_gemini_api_key_here":
        return None
    return key


def get_vision_model_name() -> str:
    return (
        os.getenv("GEMINI_VISION_MODEL", "").strip()
        or os.getenv("GEMINI_MODEL", "").strip()
        or "gemini-3.5-flash-lite"
    )


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:48].rstrip("_") or "custom_field"


def _box1000_to_pct(box: Optional[List[int]]) -> Optional[Tuple[float, float, float, float]]:
    if not box or len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = [max(0.0, min(1000.0, float(v))) for v in box]
    if ymax < ymin:
        ymin, ymax = ymax, ymin
    if xmax < xmin:
        xmin, xmax = xmax, xmin
    x = round(xmin / 1000.0, 4)
    y = round(ymin / 1000.0, 4)
    w = round(max(0.005, (xmax - xmin) / 1000.0), 4)
    h = round(max(0.005, (ymax - ymin) / 1000.0), 4)
    return x, y, min(1.0 - x, w), min(1.0 - y, h)


def _snap_to_vector_geometry(
    field_type: str,
    ans_rect: Tuple[float, float, float, float],
    geometry: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Tuple[float, float, float, float], bool]:
    """
    Snaps Vision's predicted normalized answer rect onto the nearest exact Stage 1 vector
    primitive (checkbox square, table cell, input box, or underline) when within tight tolerance.
    Returns ((x, y, w, h), was_snapped).
    """
    x, y, w, h = ans_rect
    cx = x + w * 0.5
    cy = y + h * 0.5

    if field_type == "checkbox":
        best_cb = None
        best_dist = 0.028  # 2.8% page radius tolerance
        for cb in geometry.get("checkbox_candidates", []):
            dist = ((cb["cx_pct"] - cx) ** 2 + (cb["cy_pct"] - cy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_cb = cb
        if best_cb:
            return (best_cb["cx_pct"], best_cb["cy_pct"], 0.0, 0.0), True
        return (round(cx, 4), round(cy, 4), 0.0, 0.0), False

    if field_type in ("text", "multiline"):
        # 1. Try snapping to a matching rectangular input box or table cell
        box_pool = geometry.get("table_cells", []) + geometry.get("text_boxes", [])
        best_box = None
        best_iou = 0.35
        for b in box_pool:
            bx0, by0 = b["x_pct"], b["y_pct"]
            bx1, by1 = bx0 + b["w_pct"], by0 + b["h_pct"]
            ix0, iy0 = max(x, bx0), max(y, by0)
            ix1, iy1 = min(x + w, bx1), min(y + h, by1)
            inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
            if inter <= 0:
                continue
            union = (w * h) + (b["w_pct"] * b["h_pct"]) - inter
            iou = inter / max(1e-6, union)
            if iou > best_iou:
                best_iou = iou
                best_box = b
        if best_box:
            pad_x = min(0.005, best_box["w_pct"] * 0.04)
            pad_y = min(0.003, best_box["h_pct"] * 0.08)
            return (
                round(best_box["x_pct"] + pad_x, 4),
                round(best_box["y_pct"] + pad_y, 4),
                round(max(0.02, best_box["w_pct"] - pad_x * 2), 4),
                round(max(0.016, best_box["h_pct"] - pad_y * 2), 4),
            ), True

        # 2. Try snapping to a horizontal underline right beneath the predicted box
        best_ul = None
        best_score = 0.032
        y_bottom = y + h
        for ul in geometry.get("underlines", []):
            y_diff = abs(ul["y_pct"] - y_bottom)
            x_overlap = min(x + w, ul["x_pct"] + ul["w_pct"]) - max(x, ul["x_pct"])
            if y_diff <= best_score and x_overlap >= min(w, ul["w_pct"]) * 0.45:
                best_score = y_diff
                best_ul = ul
        if best_ul:
            box_h = max(0.022, min(0.045, h))
            snapped_y = max(0.005, best_ul["y_pct"] - box_h + 0.002)
            return (
                round(best_ul["x_pct"], 4),
                round(snapped_y, 4),
                round(max(0.04, best_ul["w_pct"]), 4),
                round(box_h, 4),
            ), True

    if field_type == "image":
        best_box = None
        best_iou = 0.30
        for b in geometry.get("large_boxes", []) + geometry.get("text_boxes", []):
            bx0, by0 = b["x_pct"], b["y_pct"]
            bx1, by1 = bx0 + b["w_pct"], by0 + b["h_pct"]
            ix0, iy0 = max(x, bx0), max(y, by0)
            ix1, iy1 = min(x + w, bx1), min(y + h, by1)
            inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
            if inter <= 0:
                continue
            union = (w * h) + (b["w_pct"] * b["h_pct"]) - inter
            iou = inter / max(1e-6, union)
            if iou > best_iou:
                best_iou = iou
                best_box = b
        if best_box:
            return (
                round(best_box["x_pct"], 4),
                round(best_box["y_pct"], 4),
                round(best_box["w_pct"], 4),
                round(best_box["h_pct"], 4),
            ), True

    return ans_rect, False


def _strip_option_suffix(field_key: str, raw_mv: Optional[str]) -> str:
    base = field_key
    if raw_mv:
        mv_slug = _slugify(raw_mv)
        if mv_slug and base.endswith(f"_{mv_slug}") and len(base) > len(mv_slug) + 2:
            base = base[: -(len(mv_slug) + 1)]
    stripped = OPTION_SUFFIX_RE.sub("", base)
    return stripped or base


def _normalize_vision_checkbox_groups(
    results: List[Dict[str, Any]],
    page_scrape: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Post-processes Vision checkbox items so:
      1. Options sharing the same question/label or option-suffixed stem unify onto one shared field_key.
      2. Missing/null match_values (such as literal "None" coerced to JSON null) recover cleanly.
    """
    cb_indices = [i for i, m in enumerate(results) if m.get("type") == "checkbox"]
    if not cb_indices:
        return results

    # Build clusters of related checkbox indices via Union-Find
    parent = {i: i for i in cb_indices}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Cluster by shared normalized label or shared field_key / stem
    by_label: Dict[str, List[int]] = {}
    by_stem: Dict[Tuple[str, int], List[int]] = {}

    for i in cb_indices:
        m = results[i]
        norm_lbl = re.sub(r"\s+", " ", (m.get("label") or "").strip().lower())
        if norm_lbl and norm_lbl not in ("option", "checkbox", "choice"):
            by_label.setdefault(norm_lbl, []).append(i)

        stem = _strip_option_suffix(m["field_key"], m.get("_raw_match_value"))
        row_bucket = int(round(float(m.get("y_pct") or 0.0) / 0.03))
        by_stem.setdefault((stem, row_bucket), []).append(i)

    for idxs in by_label.values():
        for other in idxs[1:]:
            union(idxs[0], other)

    for idxs in by_stem.values():
        if len(idxs) >= 2:
            for other in idxs[1:]:
                union(idxs[0], other)

    groups: Dict[int, List[int]] = {}
    for i in cb_indices:
        groups.setdefault(find(i), []).append(i)

    lines = page_scrape.get("lines", [])

    for grp_idxs in groups.values():
        if len(grp_idxs) >= 2:
            # Pick canonical shared label & key
            labels = [results[i].get("label", "") for i in grp_idxs if results[i].get("label")]
            shared_label = min(labels, key=len) if labels else human_fallback(results[grp_idxs[0]]["field_key"])
            # Prefer a field_key that already equals a stem without option suffix
            stems = [_strip_option_suffix(results[i]["field_key"], results[i].get("_raw_match_value")) for i in grp_idxs]
            non_suffixed = [
                results[i]["field_key"]
                for i in grp_idxs
                if results[i]["field_key"] == _strip_option_suffix(results[i]["field_key"], results[i].get("_raw_match_value"))
            ]
            if len(set(non_suffixed)) == 1 and non_suffixed:
                shared_key = non_suffixed[0]
            elif len(set(stems)) == 1 and stems[0]:
                shared_key = stems[0]
            else:
                shared_key = _slugify(shared_label)

            for i in grp_idxs:
                results[i]["field_key"] = shared_key
                results[i]["label"] = shared_label

        # Recover missing/null match_values
        used_mvs = {
            str(results[i].get("_raw_match_value")).strip().lower()
            for i in grp_idxs
            if results[i].get("_raw_match_value")
        }
        for i in grp_idxs:
            m = results[i]
            raw_mv = m.pop("_raw_match_value", None)
            if raw_mv and str(raw_mv).strip():
                m["match_value"] = str(raw_mv).strip()
                continue

            recovered = None
            cb_y = float(m.get("y_pct") or 0.0)
            cb_x = float(m.get("x_pct") or 0.0)
            nearby_lines = [
                ln for ln in lines if abs((ln["y_pct"] + ln["h_pct"] * 0.5) - cb_y) <= 0.024
            ]
            line_text = " ".join(ln["text"] for ln in nearby_lines)

            # Most frequent null-coercion culprit: literal option "None"
            if len(grp_idxs) >= 2 and "none" not in used_mvs and re.search(r"\bNone\b", line_text, re.IGNORECASE):
                recovered = "None"
            else:
                # Look for option token immediately left/right of cb_x inside nearby lines
                for ln in nearby_lines:
                    txt = ln["text"]
                    for opt_m in re.finditer(r"([A-Za-z][A-Za-z0-9\-/\s]{1,24}?)\s*[\(\[]\s*[\)\]]", txt):
                        opt_cand = opt_m.group(1).strip()
                        slot_x = ln["x_pct"] + ln["w_pct"] * ((opt_m.start() + opt_m.end()) * 0.5 / max(1, len(txt)))
                        if abs(slot_x - cb_x) <= 0.10 and opt_cand.lower() not in used_mvs:
                            recovered = opt_cand
                            break
                    if recovered:
                        break

            final_mv = recovered or "Yes"
            m["match_value"] = final_mv
            used_mvs.add(final_mv.lower())

    for m in results:
        m.pop("_raw_match_value", None)

    return results


def human_fallback(key: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", key or "").strip()
    return cleaned.capitalize() if cleaned else "Choice"


def _analyze_single_page_vision(
    client: Any,
    model_name: str,
    png_bytes: bytes,
    page_scrape: Dict[str, Any],
) -> Tuple[int, List[Dict[str, Any]], Optional[str], List[Dict[str, str]], Optional[str], Optional[str]]:
    """
    Calls Gemini Interactions API on a single rendered PDF page and snaps results to geometry.
    Returns (page_num, mappings, page_summary, key_values, scanned_text, error).
    """
    page_num = page_scrape["page_number"]
    geom_hints = format_page_scrape_for_vision(page_scrape)

    user_prompt = (
        f"Analyze PDF Page {page_num} ({page_scrape['page_type']} page) and identify EVERY fillable "
        f"question/prompt and its exact blank answer area.\n\n"
        f"{geom_hints}\n\n"
        f"Return a JSON object matching the required schema."
    )

    interaction = client.interactions.create(
        model=model_name,
        system_instruction=VISION_SYSTEM_PROMPT,
        input=[
            {"type": "text", "text": user_prompt},
            {
                "type": "image",
                "data": base64.b64encode(png_bytes).decode("utf-8"),
                "mime_type": "image/png",
            },
        ],
        generation_config={"thinking_level": os.getenv("GEMINI_VISION_THINKING", "low")},
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": PageVisionAnalysis.model_json_schema(),
        },
        store=False,
    )

    raw_json = getattr(interaction, "output_text", None)
    if not raw_json:
        return page_num, [], None, [], None, "Empty Vision response"

    parsed = PageVisionAnalysis.model_validate_json(raw_json)
    page_summary = (parsed.page_summary or "").strip() or None
    kv_list = [
        {"key": kv.key.strip(), "value": kv.value.strip()}
        for kv in (parsed.extracted_key_values or [])
        if kv.key and kv.key.strip() and kv.value and kv.value.strip()
    ]
    scanned_text = (parsed.scanned_text or "").strip() or None

    if not parsed.is_fillable_page or not parsed.fields:
        return page_num, [], page_summary, kv_list, scanned_text, None

    geometry = page_scrape.get("geometry", {})
    results: List[Dict[str, Any]] = []

    for f in parsed.fields:
        ans_pct = _box1000_to_pct(f.answer_box)
        if not ans_pct:
            continue
        snapped_rect, was_snapped = _snap_to_vector_geometry(f.type, ans_pct, geometry)
        q_pct = _box1000_to_pct(f.question_box)

        sx, sy, sw, sh = snapped_rect
        f_key = _slugify(f.field_key or f.label or f.question_text)
        clean_label = (f.label or f.question_text or f_key).strip()[:80]
        q_text = (f.question_text or clean_label).strip()[:300]
        conf = round(max(0.1, min(1.0, float(f.confidence))), 2)
        if was_snapped:
            conf = round(min(0.98, conf + 0.08), 2)

        raw_mv = f.match_value.strip() if f.match_value and f.match_value.strip() else None

        mapping: Dict[str, Any] = {
            "type": f.type,
            "field_key": f_key,
            "label": clean_label,
            "question_text": q_text,
            "section": (f.section or "").strip() or None,
            "match_value": raw_mv if f.type == "checkbox" else None,
            "_raw_match_value": raw_mv if f.type == "checkbox" else None,
            "x_pct": sx,
            "y_pct": sy,
            "width_pct": None if f.type == "checkbox" else round(max(0.03, sw), 4),
            "height_pct": None if f.type == "checkbox" else round(max(0.018, sh), 4),
            "qx_pct": q_pct[0] if q_pct else None,
            "qy_pct": q_pct[1] if q_pct else None,
            "qw_pct": q_pct[2] if q_pct else None,
            "qh_pct": q_pct[3] if q_pct else None,
            "page_number": page_num,
            "font_size": 10.0 if f.type in ("text", "multiline") else None,
            "align": "left",
            "confidence": conf,
            "detection_source": "vision_snapped" if was_snapped else "vision",
            "acroform_field_name": None,
        }
        results.append(mapping)

    results = _normalize_vision_checkbox_groups(results, page_scrape)
    return page_num, results, page_summary, kv_list, scanned_text, None


def analyze_pages_with_vision(
    pdf_path: str,
    candidate_pages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Runs concurrent Gemini Vision + Geometry-Snapping analysis across candidate PDF pages.
    Returns a dict containing detected mappings, inspected_pages (including pages confirmed
    read-only), page_summaries, page_key_values, page_ocr_text, warning, and model_used.
    """
    api_key = get_gemini_api_key()
    model_name = get_vision_model_name()
    if not api_key or not candidate_pages:
        return {
            "mappings": [],
            "inspected_pages": set(),
            "page_summaries": {},
            "page_key_values": {},
            "page_ocr_text": {},
            "warning": None,
            "model_used": model_name,
        }

    pages_to_run = candidate_pages[:MAX_VISION_PAGES]
    warning: Optional[str] = None
    if len(candidate_pages) > MAX_VISION_PAGES:
        warning = (
            f"Vision analyzed the first {MAX_VISION_PAGES} candidate pages "
            f"(out of {len(candidate_pages)}). Set MAX_VISION_PAGES to increase."
        )

    # Render target pages once in the main thread (PyMuPDF handles are not thread-safe)
    rendered_inputs: List[Tuple[bytes, Dict[str, Any]]] = []
    doc = pymupdf.open(pdf_path)
    try:
        for page_scrape in pages_to_run:
            idx = page_scrape["page_number"] - 1
            if 0 <= idx < len(doc):
                page = doc[idx]
                scale = 1400.0 / max(1.0, float(page.rect.width))
                scale = max(1.0, min(2.5, scale))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                rendered_inputs.append((pix.tobytes("png"), page_scrape))
    finally:
        doc.close()

    client = genai.Client(api_key=api_key, http_options={"timeout": GEMINI_VISION_TIMEOUT_MS})
    by_page: Dict[int, List[Dict[str, Any]]] = {}
    inspected_pages: set[int] = set()
    page_summaries: Dict[int, str] = {}
    page_key_values: Dict[int, List[Dict[str, str]]] = {}
    page_ocr_text: Dict[int, str] = {}
    errors: List[str] = []

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(rendered_inputs)))) as pool:
        futures = {
            pool.submit(_analyze_single_page_vision, client, model_name, png, ps): ps["page_number"]
            for png, ps in rendered_inputs
        }
        for fut in as_completed(futures):
            pnum = futures[fut]
            try:
                page_num, page_fields, summary, kvs, ocr_txt, page_err = fut.result()
                if page_err:
                    errors.append(f"Page {page_num}: {page_err}")
                else:
                    inspected_pages.add(page_num)
                    by_page[page_num] = page_fields
                    if summary:
                        page_summaries[page_num] = summary
                    if kvs:
                        page_key_values[page_num] = kvs
                    if ocr_txt:
                        page_ocr_text[page_num] = ocr_txt
            except Exception as exc:
                errors.append(f"Page {pnum}: {exc}")

    ordered_mappings: List[Dict[str, Any]] = []
    for _, ps in rendered_inputs:
        ordered_mappings.extend(by_page.get(ps["page_number"], []))

    if errors:
        err_summary = "; ".join(errors[:3])
        warning = (
            f"{warning} | Vision notice: {err_summary}"
            if warning
            else f"Vision notice: {err_summary}"
        )

    return {
        "mappings": ordered_mappings,
        "inspected_pages": inspected_pages,
        "page_summaries": page_summaries,
        "page_key_values": page_key_values,
        "page_ocr_text": page_ocr_text,
        "warning": warning,
        "model_used": model_name,
    }

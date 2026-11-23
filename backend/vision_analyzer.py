import base64
import io
import os
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Literal, Optional, Tuple
import numpy as np
import pymupdf
from dotenv import load_dotenv
from google import genai
from PIL import Image
from pydantic import BaseModel, Field

from pdf_scraper import format_page_scrape_for_vision

load_dotenv()

DEFAULT_VISION_MODEL = (
    os.getenv("GEMINI_VISION_MODEL")
    or os.getenv("GEMINI_MODEL")
    or "gemini-3.5-flash-lite"
)
IS_VERCEL = os.getenv("VERCEL") == "1"
MAX_VISION_PAGES = int(os.getenv("MAX_VISION_PAGES", "4" if IS_VERCEL else "20"))
GEMINI_VISION_TIMEOUT_MS = int(os.getenv("GEMINI_VISION_TIMEOUT_MS", "22000" if IS_VERCEL else "45000"))
VISION_TOTAL_BUDGET_S = float(os.getenv("VISION_TOTAL_BUDGET_S", "42.0" if IS_VERCEL else "110.0"))

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
        description="Complete, self-contained question, prompt, or table row prompt printed on the PDF so the user understands it without viewing the PDF. Combine parent question + follow-up using ' — ' (e.g. 'Have you been part of a Software Development Team? — What/Where?'). Never include raw '( )' checkbox option lists here."
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
    parent_field_key: Optional[str] = Field(
        default=None,
        description="If this text/multiline field is a conditional or inline follow-up to a checkbox/choice question (e.g. 'If Yes, Project Name & Location:', 'If Other, specify:', 'Why:'), set this to the EXACT field_key of the parent checkbox question it belongs to; otherwise null.",
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
1. Pure read-only informational prose, headings, instructions, and logos -> IGNORE these for `fields`, though you may summarize already-printed facts in `extracted_key_values`.
   IMPORTANT EXCEPTION FOR AGREEMENTS, UNDERTAKINGS & LEGAL DECLARATIONS: Clauses under headings like "Agreement", "Undertaking", "Declaration", "Attestation", "Consent", or "Warranty" very often contain inline fill-in-the-blank leaders — dotted lines (`..............`), dashed lines (`--------`), underscores (`________`), or gaps inside sentences (e.g. `I/we ................ a subscriber to ...`, `I, __________, hereby declare...`, `Dated this ____ day of ______ 20__`, `Witnessed by ..............`). NEVER skip these blanks under rule 1. Extract EVERY such inline blank as `type="text"` with `answer_box` strictly over the dotted/underlined leader (not over `I/we` or surrounding words), a clear human-readable `label` (e.g. `"Subscriber / Declarant Full Name"`, `"Agreement Day"` — NEVER bare `"I/we"`), and a contextual `question_text` quoting the surrounding clause.
2. Actual QUESTIONS / PROMPTS that expect a user to fill in an answer, tick a checkbox/radio (including `(  )` or `[  ]` blanks), attach a photo/stamp, or sign -> EXTRACT every single one.

CRITICAL RULES FOR `answer_box` ([ymin, xmin, ymax, xmax] on 0-1000 scale):
- `answer_box` MUST mark the EMPTY BLANK SPACE (or dotted/underlined leader) where the answer goes (to the right of a label on an underline, inside an empty box/table cell, inside a small checkbox square/circle or `(  )` blank, inside a blank gap in a sentence, or directly above a signature line).
- NEVER place `answer_box` on top of the printed question text itself.
- SPLIT-LINE & CURRENCY-DELIMITED FIELDS: NEVER span one `answer_box` across a printed currency symbol or inline divider (`₦`, `$`, `£`, `€`, `¥`, `NGN`, `USD`, `/`, `to`) that separates two blanks on a row (e.g. `Total Cost: ____ (amount in word) ____` followed by `________ ₦ ________`). Emit separate fields so the words box ends cleanly before any divider/symbol and the figures box starts strictly to the RIGHT of the printed currency symbol (`₦`, `$`, etc.). Include the qualifier in BOTH `label` and `question_text` (e.g. `label: "Total Cost (Amount in words)"`, `question_text: "Total Cost (Amount in words)"` and `label: "Total Cost (Amount in figures, ₦)"`, `question_text: "Total Cost (Amount in figures, ₦)"`).
- For `checkbox` / radio options: emit ONE entry per option box or `(  )` slot, and ALL checkbox/radio options belonging to the same question MUST share the EXACT SAME `field_key` and `label` (do NOT append `_yes`, `_no`, `_ongoing`, etc. to `field_key`).
- SAME-LINE & NEXT-LINE CONDITIONAL FOLLOW-UPS: Whenever a row, table cell, or the very next line contains a conditional/inline write-in prompt tied to a checkbox/choice question (e.g. `Yes ( ) No ( ) What/Where?`, `Yes ( ) No ( ) Why:`, `If Yes, Project Name & Location:`, `If Other, please specify:`, `Ongoing ( ) Completed ( ) Date of Completion:`, `Yes ( ) No ( ) Exempted ( ) NYSC Date:`), emit BOTH the checkbox entries AND a separate `type="text"` field for the blank write-in area. When two different questions share the same row (e.g. `Radio __ Others __ | Do you own any property...? Yes __ No __`) and the next line asks `If Yes, ...`, match the condition (`Yes`) to the parent question whose options actually include that trigger! Set BOTH `parent_field_key` to that parent's exact `field_key` AND `question_text` to `"<Parent Question> — <Follow-up Prompt>"` (e.g. `"Do you own any property with Zylus homes and Property? — If Yes, Project Name & Location:"`). NEVER leave `question_text` as bare `"Why:"` or `"What/Where?"`, NEVER include raw `( )` checkbox options inside a text field's `label` or `question_text`, and set `parent_field_key: null` for ordinary non-followup fields.
- COMPLETE QUESTION TEXT: For every field (`checkbox`, `text`, `multiline`, `image`), `question_text` MUST be the full, self-contained question from the PDF so a user can answer accurately without opening the PDF.
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
            return (
                best_cb["cx_pct"],
                best_cb["cy_pct"],
                round(float(best_cb.get("w_pct") or 0.0), 4),
                round(float(best_cb.get("h_pct") or 0.0), 4),
            ), True
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
    key_remap: Dict[str, str] = {}

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
                orig_fk = results[i]["field_key"]
                orig_stem = _strip_option_suffix(orig_fk, results[i].get("_raw_match_value"))
                if orig_fk != shared_key:
                    key_remap[orig_fk] = shared_key
                if orig_stem and orig_stem != shared_key:
                    key_remap[orig_stem] = shared_key
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
        pk = m.get("_parent_field_key")
        if pk and pk in key_remap:
            m["_parent_field_key"] = key_remap[pk]

    return results


def human_fallback(key: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", key or "").strip()
    return cleaned.capitalize() if cleaned else "Choice"


def _norm_option_token(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _snap_scanned_checkbox_in_image(
    gray_arr: np.ndarray,
    vx: float,
    vy: float,
    pw_pt: float,
    ph_pt: float,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Locates a hollow square/circle checkbox contour near `(vx, vy)` on a scanned page raster
    using lightweight local NumPy thresholding and 4-connected component analysis.
    """
    img_h, img_w = gray_arr.shape
    if img_h < 20 or img_w < 20:
        return None

    pt_per_px_x = max(0.1, pw_pt / img_w)
    pt_per_px_y = max(0.1, ph_pt / img_h)

    cx_px = int(round(vx * img_w))
    cy_px = int(round(vy * img_h))
    rx = max(24, int(round(24.0 / pt_per_px_x)))
    ry = max(20, int(round(20.0 / pt_per_px_y)))

    px0 = max(0, cx_px - rx)
    px1 = min(img_w, cx_px + rx)
    py0 = max(0, cy_px - ry)
    py1 = min(img_h, cy_px + ry)

    patch = gray_arr[py0:py1, px0:px1]
    ph_p, pw_p = patch.shape
    if ph_p < 8 or pw_p < 8:
        return None

    bg = float(np.percentile(patch, 80))
    thresh = max(100.0, min(195.0, bg - 42.0))
    dark = patch < thresh

    visited = np.zeros((ph_p, pw_p), dtype=bool)
    best_dist = 22.0
    best_box: Optional[Tuple[float, float, float, float]] = None

    for sy in range(ph_p):
        for sx in range(pw_p):
            if not dark[sy, sx] or visited[sy, sx]:
                continue
            q = deque([(sy, sx)])
            visited[sy, sx] = True
            min_x = max_x = sx
            min_y = max_y = sy
            area = 0

            while q:
                cy_i, cx_i = q.popleft()
                area += 1
                if cx_i < min_x:
                    min_x = cx_i
                if cx_i > max_x:
                    max_x = cx_i
                if cy_i < min_y:
                    min_y = cy_i
                if cy_i > max_y:
                    max_y = cy_i
                for ny, nx in ((cy_i - 1, cx_i), (cy_i + 1, cx_i), (cy_i, cx_i - 1), (cy_i, cx_i + 1)):
                    if 0 <= ny < ph_p and 0 <= nx < pw_p and dark[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        q.append((ny, nx))

            if area < 10 or area > int(patch.size * 0.45):
                continue

            cw = max_x - min_x + 1
            ch = max_y - min_y + 1
            w_pt = cw * pt_per_px_x
            h_pt = ch * pt_per_px_y
            if not (6.0 <= w_pt <= 24.0 and 6.0 <= h_pt <= 24.0):
                continue
            if not (0.65 <= (w_pt / max(0.1, h_pt)) <= 1.55):
                continue

            # Ensure interior core is mostly white/hollow
            ix0 = min_x + max(1, int(round(cw * 0.28)))
            ix1 = max_x - max(1, int(round(cw * 0.28))) + 1
            iy0 = min_y + max(1, int(round(ch * 0.28)))
            iy1 = max_y - max(1, int(round(ch * 0.28))) + 1
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inner_dark = float(np.mean(dark[iy0:iy1, ix0:ix1]))
            if inner_dark >= 0.35:
                continue

            comp_cx = px0 + (min_x + max_x + 1) * 0.5
            comp_cy = py0 + (min_y + max_y + 1) * 0.5
            dist_pt = (
                ((comp_cx - cx_px) * pt_per_px_x) ** 2 + ((comp_cy - cy_px) * pt_per_px_y) ** 2
            ) ** 0.5
            if dist_pt <= best_dist:
                best_dist = dist_pt
                best_box = (
                    round(comp_cx / img_w, 4),
                    round(comp_cy / img_h, 4),
                    round(cw / img_w, 4),
                    round(ch / img_h, 4),
                )

    return best_box


def _snap_vision_checkboxes(
    results: List[Dict[str, Any]],
    geometry: Dict[str, List[Dict[str, Any]]],
    page_scrape: Dict[str, Any],
    png_bytes: Optional[bytes] = None,
) -> List[Dict[str, Any]]:
    """
    Post-normalization 3-tier checkbox snapper:
      1. Row + Option-Label Match across Stage 1 `checkbox_candidates` and `radio_glyphs`
         (recovers large Vision horizontal drifts such as 47pt offsets on multi-option rows).
      2. Nearest unused `checkbox_candidates` / `radio_glyphs` within tight proximity.
      3. Scanned-image hollow contour snap (Pillow/NumPy) when no vector/text layer exists.
    """
    cb_pool = geometry.get("checkbox_candidates", [])
    radio_pool = geometry.get("radio_glyphs", [])
    claimed_cb: set[int] = set()
    claimed_radio: set[int] = set()
    gray_arr: Optional[np.ndarray] = None
    pw_pt = float(page_scrape.get("width") or 595.0)
    ph_pt = float(page_scrape.get("height") or 842.0)

    def _pick_best(vx: float, vy: float, mv_norm: str) -> Optional[Tuple[str, int, Dict[str, Any]]]:
        best_rank: Optional[Tuple[int, int, float]] = None
        best_hit: Optional[Tuple[str, int, Dict[str, Any]]] = None

        pools: List[Tuple[str, int, List[Dict[str, Any]], set[int]]] = [
            ("cb", 0, cb_pool, claimed_cb),
            ("radio", 1, radio_pool, claimed_radio),
        ]

        # Tier 1: Same horizontal row + label_before / label_after match
        if mv_norm:
            for pool_name, pool_prio, items, claimed in pools:
                for idx, cand in enumerate(items):
                    if idx in claimed:
                        continue
                    dy = abs(float(cand["cy_pct"]) - vy)
                    dx = abs(float(cand["cx_pct"]) - vx)
                    if dy > 0.025 or dx > 0.14:
                        continue
                    lb_n = _norm_option_token(cand.get("label_before"))
                    la_n = _norm_option_token(cand.get("label_after"))
                    if mv_norm in (lb_n, la_n):
                        match_tier = 0
                    elif len(mv_norm) >= 3 and any(
                        tok and (mv_norm in tok or tok in mv_norm) for tok in (lb_n, la_n)
                    ):
                        match_tier = 1
                    else:
                        continue
                    rank = (match_tier, pool_prio, dy * 4.0 + dx)
                    if best_rank is None or rank < best_rank:
                        best_rank = rank
                        best_hit = (pool_name, idx, cand)
            if best_hit is not None:
                return best_hit

        # Tier 2: Nearest unused candidate within tight proximity
        best_dist = 0.032
        for pool_name, pool_prio, items, claimed in pools:
            radius_limit = 0.032 if pool_name == "cb" else 0.028
            for idx, cand in enumerate(items):
                if idx in claimed:
                    continue
                dist = ((float(cand["cx_pct"]) - vx) ** 2 + (float(cand["cy_pct"]) - vy) ** 2) ** 0.5
                if dist < min(best_dist, radius_limit):
                    best_dist = dist
                    best_hit = (pool_name, idx, cand)
        return best_hit

    for m in results:
        if m.get("type") != "checkbox":
            continue
        vx = float(m["x_pct"])
        vy = float(m["y_pct"])
        mv_norm = _norm_option_token(m.get("match_value"))

        hit = _pick_best(vx, vy, mv_norm)
        if hit is not None:
            pool_name, idx, cand = hit
            if pool_name == "cb":
                claimed_cb.add(idx)
            else:
                claimed_radio.add(idx)
            m["x_pct"] = cand["cx_pct"]
            m["y_pct"] = cand["cy_pct"]
            m["width_pct"] = cand.get("w_pct")
            m["height_pct"] = cand.get("h_pct")
            m["detection_source"] = "vision_snapped"
            m["confidence"] = round(min(0.98, float(m.get("confidence") or 0.85) + 0.08), 2)
            continue

        # Tier 3: Scanned image contour snap when no vector/text candidate exists
        if (page_scrape.get("page_type") == "scanned_image" or not cb_pool) and png_bytes:
            if gray_arr is None:
                try:
                    with Image.open(io.BytesIO(png_bytes)) as im:
                        gray_arr = np.asarray(im.convert("L"), dtype=np.uint8)
                except Exception:
                    gray_arr = np.empty((0, 0), dtype=np.uint8)
            if gray_arr.size > 0:
                contour = _snap_scanned_checkbox_in_image(gray_arr, vx, vy, pw_pt, ph_pt)
                if contour is not None:
                    m["x_pct"], m["y_pct"], m["width_pct"], m["height_pct"] = contour
                    m["detection_source"] = "vision_snapped"
                    m["confidence"] = round(min(0.96, float(m.get("confidence") or 0.82) + 0.06), 2)

    return results


_INLINE_OBSTACLE_RE = re.compile(r"^(?:[₦$£€¥/]|ngn|usd|gbp|eur)$", re.IGNORECASE)
_INLINE_CURRENCY_CHARS_RE = re.compile(r"(?:^|[\s_])([₦$£€¥])(?:[\s_]|$)")
_WORDS_FIELD_RE = re.compile(r"\bword(?:s)?\b", re.IGNORECASE)
_FIGURES_FIELD_RE = re.compile(
    r"\b(?:figure|figures|numeric|number|amount|cost|price|fee|total|naira|sum|salary|deposit|balance|payment)\b",
    re.IGNORECASE,
)


def _find_interior_digital_obstacle(
    lines: List[Dict[str, Any]],
    x: float,
    y: float,
    w: float,
    h: float,
) -> Optional[Tuple[float, float]]:
    """Finds a single short interior divider/currency glyph in scraped digital text lines."""
    hits: List[Tuple[float, float]] = []
    min_cx = x + w * 0.20
    max_cx = x + w * 0.80
    for ln in lines:
        ly0 = float(ln["y_pct"])
        ly1 = ly0 + float(ln["h_pct"])
        if ly1 < y - 0.008 or ly0 > y + h + 0.008:
            continue
        txt = (ln.get("text") or "").strip()
        if not txt:
            continue
        if len(txt) <= 5 and _INLINE_OBSTACLE_RE.match(txt):
            obs_cx = ln["x_pct"] + ln["w_pct"] * 0.5
            if min_cx <= obs_cx <= max_cx:
                hits.append((float(ln["x_pct"]), float(ln["x_pct"] + ln["w_pct"])))
            continue
        for cm in _INLINE_CURRENCY_CHARS_RE.finditer(txt):
            c_ratio0 = cm.start(1) / max(1, len(txt))
            c_ratio1 = cm.end(1) / max(1, len(txt))
            ox0 = float(ln["x_pct"] + ln["w_pct"] * c_ratio0)
            ox1 = float(ln["x_pct"] + ln["w_pct"] * c_ratio1)
            obs_cx = (ox0 + ox1) * 0.5
            if min_cx <= obs_cx <= max_cx:
                hits.append((ox0, ox1))

    if len(hits) == 1:
        return hits[0]
    return None


def _find_interior_scanned_obstacle(
    gray_arr: np.ndarray,
    x: float,
    y: float,
    w: float,
    h: float,
) -> Optional[Tuple[float, float]]:
    """
    Detects an isolated tall printed symbol (such as a central ₦, $, £, /) crossing an otherwise
    thin blank underline on a scanned raster page. Returns normalized (obs_x0, obs_x1) or None.
    """
    img_h, img_w = gray_arr.shape
    if img_h < 20 or img_w < 20:
        return None

    px0 = max(0, int(round(x * img_w)))
    px1 = min(img_w, int(round((x + w) * img_w)))
    py0 = max(0, int(round((y - 0.008) * img_h)))
    py1 = min(img_h, int(round((y + h + 0.006) * img_h)))
    if px1 - px0 < 20 or py1 - py0 < 8:
        return None

    crop = gray_arr[py0:py1, px0:px1] < 140
    col_counts = crop.sum(axis=0)
    if col_counts.size == 0:
        return None

    # Only trim when most of the band is blank/thin underline (avoid multi-word prose paragraphs)
    med_ink = float(np.median(col_counts))
    p90_ink = float(np.percentile(col_counts, 90))
    if med_ink > 5.0 or p90_ink > 6.0:
        return None

    # Use baseline-relative connectivity threshold so wide double-bar glyphs (like ₦) stay one run,
    # while requiring the cluster's peak height to be genuinely tall.
    ink_thresh = max(8, int(round(p90_ink)) + 5)
    tall_cols = np.where(col_counts >= ink_thresh)[0]
    if len(tall_cols) == 0:
        return None

    bridge_px = max(6, int(round(img_w * 0.008)))
    raw_runs: List[Tuple[int, int]] = []
    start_c = prev_c = int(tall_cols[0])
    for col in tall_cols[1:]:
        c_int = int(col)
        if c_int - prev_c > bridge_px:
            raw_runs.append((start_c, prev_c))
            start_c = c_int
        prev_c = c_int
    raw_runs.append((start_c, prev_c))

    peak_thresh = max(12, int((py1 - py0) * 0.25))
    runs = [(s, e) for s, e in raw_runs if int(col_counts[s : e + 1].max()) >= peak_thresh]
    if len(runs) != 1:
        return None

    run_s, run_e = runs[0]
    obs_x0 = (px0 + run_s) / img_w
    obs_x1 = (px0 + run_e + 1) / img_w
    obs_w = obs_x1 - obs_x0
    obs_cx = (obs_x0 + obs_x1) * 0.5
    if not (0.006 <= obs_w <= 0.08):
        return None
    if not (x + w * 0.25 <= obs_cx <= x + w * 0.75):
        return None
    return obs_x0, obs_x1


def _trim_boxes_around_inline_obstacles(
    results: List[Dict[str, Any]],
    page_scrape: Dict[str, Any],
    png_bytes: Optional[bytes] = None,
) -> List[Dict[str, Any]]:
    """
    Safety net for wide single-line text boxes that span across an interior printed currency
    symbol or inline divider (e.g. `________ ₦ ________`). Trims the figures/numeric box to
    start strictly after the symbol (or trims a words box to end before it).
    """
    if not results:
        return results

    lines = page_scrape.get("lines", [])
    gray_arr: Optional[np.ndarray] = None

    for m in results:
        if m.get("type") != "text":
            continue
        x = float(m.get("x_pct") or 0.0)
        y = float(m.get("y_pct") or 0.0)
        w = float(m.get("width_pct") or 0.0)
        h = float(m.get("height_pct") or 0.0)
        if w < 0.35 or h > 0.045:
            continue

        obs: Optional[Tuple[float, float]] = None
        if lines:
            obs = _find_interior_digital_obstacle(lines, x, y, w, h)
        if obs is None and png_bytes and (page_scrape.get("page_type") == "scanned_image" or not lines):
            if gray_arr is None:
                try:
                    with Image.open(io.BytesIO(png_bytes)) as im:
                        gray_arr = np.asarray(im.convert("L"), dtype=np.uint8)
                except Exception:
                    gray_arr = np.empty((0, 0), dtype=np.uint8)
            if gray_arr.size > 0:
                obs = _find_interior_scanned_obstacle(gray_arr, x, y, w, h)

        if obs is None:
            continue

        obs_x0, obs_x1 = obs
        combined = f"{m.get('field_key', '')} {m.get('label', '')} {m.get('question_text', '')}"
        is_words = bool(_WORDS_FIELD_RE.search(combined))
        is_figures = (not is_words) and bool(_FIGURES_FIELD_RE.search(combined))
        has_words_above = any(
            other is not m
            and other.get("type") in ("text", "multiline")
            and _WORDS_FIELD_RE.search(
                f"{other.get('field_key', '')} {other.get('label', '')} {other.get('question_text', '')}"
            )
            and 0.0 < (y - float(other.get("y_pct") or 0.0)) <= 0.06
            and (
                min(x + w, float(other["x_pct"]) + float(other.get("width_pct") or 0.0))
                - max(x, float(other["x_pct"]))
                > 0.10
            )
            for other in results
        )

        if is_figures or has_words_above:
            new_x = round(obs_x1 + 0.006, 4)
            new_w = round((x + w) - new_x, 4)
            if new_w >= 0.10:
                m["x_pct"] = new_x
                m["width_pct"] = new_w
                m["detection_source"] = "vision_snapped"
        elif is_words:
            new_w = round(obs_x0 - x - 0.006, 4)
            if new_w >= 0.10:
                m["width_pct"] = new_w
                m["detection_source"] = "vision_snapped"

    return results


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

    scanned_checklist = ""
    if page_scrape.get("page_type") == "scanned_image":
        scanned_checklist = (
            "\n\nSCANNED PAGE ACCURACY CHECKLIST:\n"
            "- Scan ALL Agreements, Undertakings, Declarations, and Consent paragraphs for inline dotted/dashed/underlined blanks (e.g. `I/we ........... a subscriber...`, `Dated this ____ day of ______`). Extract each blank over its dotted/underlined leader with a descriptive label.\n"
            "- For split rows or currency-divided lines (`________ ₦ ________`, `$`, etc.), keep figures boxes strictly to the RIGHT of the currency symbol and put `(amount in words)` / `(amount in figures)` in both `label` and `question_text`.\n"
            "- For next-line conditional follow-ups (`If Yes, ...`, `If Other, ...`), set `parent_field_key` to the matching parent checkbox question (never an unrelated question sharing that row)."
        )

    user_prompt = (
        f"Analyze PDF Page {page_num} ({page_scrape['page_type']} page) and identify EVERY fillable "
        f"question/prompt and its exact blank answer area.{scanned_checklist}\n\n"
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
        if f.type == "checkbox":
            ax, ay, aw, ah = ans_pct
            snapped_rect = (round(ax + aw * 0.5, 4), round(ay + ah * 0.5, 4), 0.0, 0.0)
            was_snapped = False
        else:
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
            "_parent_field_key": (
                _slugify(f.parent_field_key)
                if f.parent_field_key and f.parent_field_key.strip()
                else None
            ),
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
    results = _snap_vision_checkboxes(results, geometry, page_scrape, png_bytes=png_bytes)
    results = _trim_boxes_around_inline_obstacles(results, page_scrape, png_bytes=png_bytes)
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
    target_px_width = 1100.0 if IS_VERCEL else 1400.0
    doc = pymupdf.open(pdf_path)
    try:
        for page_scrape in pages_to_run:
            idx = page_scrape["page_number"] - 1
            if 0 <= idx < len(doc):
                page = doc[idx]
                scale = target_px_width / max(1.0, float(page.rect.width))
                scale = max(1.0, min(2.0 if IS_VERCEL else 2.5, scale))
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

    pool = ThreadPoolExecutor(max_workers=min(4, max(1, len(rendered_inputs))))
    futures = {
        pool.submit(_analyze_single_page_vision, client, model_name, png, ps): ps["page_number"]
        for png, ps in rendered_inputs
    }
    try:
        for fut in as_completed(futures, timeout=VISION_TOTAL_BUDGET_S):
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
    except TimeoutError:
        unfinished = [str(pnum) for f, pnum in futures.items() if not f.done()]
        errors.append(f"Vision time budget reached (remaining pages {', '.join(unfinished)} used fast geometry fallback)")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

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

import re
from typing import Any, Dict, List, Optional, Tuple
from models import DetectedFieldSummary, DictionaryFormatResponse
from pdf_scraper import scrape_pdf_document, summarize_scraped_for_storage
from vision_analyzer import analyze_pages_with_vision, get_gemini_api_key

# Universal human-readable labels for common cross-domain field keys
CANONICAL_LABELS: Dict[str, str] = {
    "first_name": "First name",
    "last_name": "Last name",
    "middle_name": "Middle name",
    "surname": "Surname / Last name",
    "other_names": "Other names",
    "full_name": "Full name",
    "title": "Title",
    "gender": "Gender",
    "marital_status": "Marital status",
    "date_of_birth": "Date of birth",
    "nationality": "Nationality",
    "citizenship": "Citizenship",
    "address": "Address",
    "street_address": "Street address",
    "residential_address": "Residential address",
    "mailing_address": "Mailing address",
    "city": "City",
    "state": "State / Province",
    "postal_code": "Postal / ZIP code",
    "country": "Country",
    "email": "Email address",
    "phone_number": "Phone number",
    "alt_phone_number": "Alternative phone number",
    "id_number": "ID / Passport number",
    "tax_id": "Tax ID / SSN",
    "occupation": "Occupation / Job title",
    "employer_name": "Employer / Organization",
    "company_name": "Company / Organization name",
    "department": "Department",
    "emergency_contact_name": "Emergency contact name",
    "emergency_contact_phone": "Emergency contact phone",
    "emergency_contact_relationship": "Emergency contact relationship",
    "bank_name": "Bank name",
    "bank_account_name": "Account holder name",
    "bank_account_number": "Account number",
    "amount": "Amount",
    "notes": "Notes / Comments",
    "date_signed": "Date",
    "profile_photo": "Profile / ID photo",
    "applicant_signature": "Signature",
    "witness_signature": "Witness signature",
    "company_stamp": "Official stamp / Seal",
}

# Universal cross-domain synonym patterns (raw label -> (canonical_key, clean_label))
RAW_LABEL_SYNONYMS: List[Tuple[str, str, str]] = [
    (r"^first\s*name$", "first_name", "First name"),
    (r"^(?:last\s*name|family\s*name)$", "last_name", "Last name"),
    (r"^surname$", "surname", "Surname / Last name"),
    (r"^middle\s*name$", "middle_name", "Middle name"),
    (r"^(?:other\s*names?|given\s*names?)$", "other_names", "Other names"),
    (
        r"^(?:full\s*name|applicant'?s?\s*name|candidate'?s?\s*name|patient'?s?\s*name|"
        r"employee'?s?\s*name|student'?s?\s*name|customer'?s?\s*name|client'?s?\s*name|"
        r"member'?s?\s*name|name\s*of\s*applicant|name\s*of\s*person|printed\s*name|name)$",
        "full_name",
        "Full name",
    ),
    (r"^title$", "title", "Title"),
    (r"^(?:date\s*of\s*birth|d\.?o\.?b\.?|birth\s*date)$", "date_of_birth", "Date of birth"),
    (r"^nationality$", "nationality", "Nationality"),
    (r"^citizenship$", "citizenship", "Citizenship"),
    (
        r"^(?:residential\s*address|home\s*address|street\s*address|contact\s*address|address)$",
        "residential_address",
        "Residential address",
    ),
    (r"^(?:mailing\s*address|postal\s*address|permanent\s*address)$", "mailing_address", "Mailing address"),
    (r"^(?:city|town)$", "city", "City"),
    (r"^(?:state|province|region|state\s*/\s*province)$", "state", "State / Province"),
    (r"^(?:zip|zip\s*code|postal\s*code|postcode|zip\s*/\s*postal\s*code)$", "postal_code", "Postal / ZIP code"),
    (r"^country$", "country", "Country"),
    (r"^(?:e-?mail(?:\s*address)?)$", "email", "Email address"),
    (
        r"^(?:phone(?:\s*(?:no|number))?|mobile(?:\s*(?:no|number))?|tel(?:ephone)?(?:\s*(?:no|number))?|cell\s*phone)$",
        "phone_number",
        "Phone number",
    ),
    (r"^(?:alt(?:ernative)?\s*(?:phone|mobile|tel)|secondary\s*phone|home\s*phone)$", "alt_phone_number", "Alternative phone number"),
    (r"^(?:occupation|profession|job\s*title|position|role|designation)$", "occupation", "Occupation / Job title"),
    (r"^(?:employer(?:'?s?\s*name)?|organization|company(?:\s*name)?|workplace|business\s*name)$", "employer_name", "Employer / Organization"),
    (r"^department$", "department", "Department"),
    (r"^(?:emergency\s*contact(?:\s*name)?|next\s*of\s*kin(?:\s*name)?)$", "emergency_contact_name", "Emergency contact name"),
    (r"^(?:emergency\s*contact\s*(?:phone|tel|number)|next\s*of\s*kin\s*(?:phone|tel|number))$", "emergency_contact_phone", "Emergency contact phone"),
    (r"^(?:emergency\s*contact\s*relationship|next\s*of\s*kin\s*relationship|relationship)$", "emergency_contact_relationship", "Emergency contact relationship"),
    (r"^(?:bank\s*name|name\s*of\s*bank)$", "bank_name", "Bank name"),
    (r"^(?:account\s*(?:holder\s*)?name)$", "bank_account_name", "Account holder name"),
    (r"^(?:account\s*(?:no|number))$", "bank_account_number", "Account number"),
    (r"^(?:gender|sex)$", "gender", "Gender"),
    (r"^marital\s*status$", "marital_status", "Marital status"),
    (r"^(?:date|date\s*signed|signature\s*date|today'?s?\s*date)$", "date_signed", "Date"),
]

# Non-question boilerplate / structural lines to ignore in offline geometry detection
IGNORE_LINE_PATTERNS = re.compile(
    r"^(?:page\s*\d+(?:\s*of\s*\d+)?|section\s*[a-z0-9]+|part\s*[a-z0-9]+|"
    r"terms\s*(?:and|&)\s*conditions|instructions?\s*:?|please\s*(?:read|complete|fill|note)|"
    r"for\s*official\s*use\s*only|office\s*use\s*only|confidential|thank\s*you|"
    r"www\.|https?://|copyright|all\s*rights\s*reserved)",
    re.IGNORECASE,
)

PHOTO_KEYWORDS = re.compile(
    r"\b(?:passport\s*photo(?:graph)?|affix\s*(?:recent\s*)?photo|attach\s*photo|profile\s*photo|photo(?:graph)?\s*here|headshot|id\s*photo|paste\s*photo)\b",
    re.IGNORECASE,
)

SIGNATURE_KEYWORDS = re.compile(
    r"\b(?:signature|sign\s*here|signed\s*by|authorized\s*sign|applicant'?s?\s*sign|witness'?s?\s*sign|initials?)\b",
    re.IGNORECASE,
)

STAMP_KEYWORDS = re.compile(
    r"\b(?:official\s*stamp|company\s*stamp|seal|stamp\s*here)\b",
    re.IGNORECASE,
)


def humanize_key(field_key: str, explicit_label: Optional[str] = None) -> str:
    """Returns a clean human-readable label for any field_key."""
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()
    if field_key in CANONICAL_LABELS:
        return CANONICAL_LABELS[field_key]
    cleaned = re.sub(r"[_\-]+", " ", field_key or "").strip()
    if not cleaned:
        return "Field"
    return cleaned[0].upper() + cleaned[1:]


def normalize_label_to_key_and_label(raw_label: str) -> Tuple[str, str]:
    """
    Converts any raw label or question extracted from a PDF into a clean
    (field_key, human_label) tuple while preserving domain-agnostic semantics.
    """
    cleaned = (raw_label or "").strip()
    # Remove leading list numbering like "1. ", "(a) ", "Q2: "
    cleaned = re.sub(r"^(?:q\d+[\.\:\)]\s*|\(?[a-z0-9]{1,3}[\.\)]\s*|[•\-\*]+\s*)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s\:\.\_\-\*\/]+$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned:
        return "custom_field", "Custom field"

    lower_clean = cleaned.lower()
    for pattern, canonical_key, canonical_label in RAW_LABEL_SYNONYMS:
        if re.match(pattern, lower_clean, re.IGNORECASE):
            return canonical_key, canonical_label

    key = re.sub(r"[^a-z0-9]+", "_", lower_clean).strip("_")
    if not key:
        key = "custom_field"
    if len(key) > 48:
        key = key[:48].rstrip("_")

    if cleaned.isupper() and len(cleaned) > 4:
        nice_label = cleaned.capitalize()
    else:
        nice_label = cleaned[0].upper() + cleaned[1:]

    if len(nice_label) > 64:
        nice_label = nice_label[:61].rstrip() + "..."

    return key, nice_label


def _is_cryptic_widget_name(name: str) -> bool:
    """Checks if a native AcroForm widget name is auto-generated / non-descriptive (e.g. Text1, f1_01[0])."""
    n = (name or "").strip()
    if not n or len(n) <= 2:
        return True
    if re.match(r"^(?:text|field|check\s*box|checkbox|radio|group|button|combo|list|sig|f\d+)[_\-\s\[\]0-9]*$", n, re.IGNORECASE):
        return True
    return False


def _find_nearest_label_for_rect(
    rx: float,
    ry: float,
    rw: float,
    rh: float,
    lines: List[Dict[str, Any]],
    allow_right: bool = False,
) -> Optional[Dict[str, Any]]:
    """Finds the most likely question/label text line adjacent to a given normalized rectangle."""
    best_line = None
    best_score = 999.0
    rcy = ry + rh * 0.5

    for ln in lines:
        txt = ln["text"].strip()
        if len(txt) < 2 or len(txt) > 140 or IGNORE_LINE_PATTERNS.search(txt):
            continue
        lx0, ly0 = ln["x_pct"], ln["y_pct"]
        lx1, ly1 = lx0 + ln["w_pct"], ly0 + ln["h_pct"]
        lcy = (ly0 + ly1) * 0.5

        # 1. Directly to the LEFT on the same row (highest preference for text inputs)
        if abs(lcy - rcy) <= max(0.018, rh * 0.85) and lx1 <= rx + 0.015:
            h_gap = rx - lx1
            if -0.01 <= h_gap <= 0.28:
                score = h_gap + abs(lcy - rcy) * 2.0
                if score < best_score:
                    best_score = score
                    best_line = ln

        # 2. Directly ABOVE the input box (left-aligned or overlapping horizontally)
        v_gap = ry - ly1
        if -0.005 <= v_gap <= 0.042:
            x_overlap = min(rx + rw, lx1) - max(rx, lx0)
            if x_overlap > -0.02 and abs(lx0 - rx) <= 0.12:
                score = 0.03 + v_gap * 2.2 + abs(lx0 - rx) * 0.5
                if score < best_score:
                    best_score = score
                    best_line = ln

        # 3. Directly to the RIGHT (common for checkboxes where box precedes option text)
        if allow_right and abs(lcy - rcy) <= max(0.018, rh * 0.9):
            r_gap = lx0 - (rx + rw)
            if -0.006 <= r_gap <= 0.08:
                score = r_gap * 0.9 + abs(lcy - rcy) * 2.0
                if score < best_score:
                    best_score = score
                    best_line = ln

    return best_line


def _current_section_for_y(y_pct: float, sections: List[Dict[str, Any]]) -> Optional[str]:
    current = None
    for s in sections:
        if s["y_pct"] <= y_pct + 0.005:
            current = s["title"]
        else:
            break
    return current


# =============================================================================
# STAGE 2: NATIVE ACROFORM EXTRACTOR WITH NEAREST-LABEL Q->A RESOLVER
# =============================================================================
def _extract_acroform_mappings(page_scrape: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_num = page_scrape["page_number"]
    widgets = page_scrape.get("widgets", [])
    lines = page_scrape.get("lines", [])
    sections = page_scrape.get("sections", [])
    mappings: List[Dict[str, Any]] = []

    # Group radio buttons by native field_name so all options share one field_key
    radio_groups: Dict[str, List[Dict[str, Any]]] = {}
    for w in widgets:
        if w["kind"] == "radio" and w["field_name"]:
            radio_groups.setdefault(w["field_name"], []).append(w)

    # Compute a group-level label for each radio group
    radio_group_meta: Dict[str, Tuple[str, str, str, Optional[Dict[str, Any]]]] = {}
    for group_name, items in radio_groups.items():
        top_item = min(items, key=lambda it: (it["y_pct"], it["x_pct"]))
        raw_group = top_item["field_label"] or group_name
        nearest_q = _find_nearest_label_for_rect(
            top_item["x_pct"], top_item["y_pct"], top_item["w_pct"], top_item["h_pct"], lines
        )
        if _is_cryptic_widget_name(raw_group) and nearest_q:
            q_text = nearest_q["text"]
            f_key, f_label = normalize_label_to_key_and_label(q_text)
        else:
            q_text = nearest_q["text"] if nearest_q else raw_group
            f_key, f_label = normalize_label_to_key_and_label(raw_group)
        radio_group_meta[group_name] = (f_key, f_label, q_text, nearest_q)

    for idx, w in enumerate(widgets):
        kind = w["kind"]
        raw_name = w["field_label"] or w["field_name"] or f"field_{idx + 1}"
        section = _current_section_for_y(w["y_pct"], sections)

        if kind == "radio" and w["field_name"] in radio_group_meta:
            f_key, f_label, q_text, q_line = radio_group_meta[w["field_name"]]
            opt_line = _find_nearest_label_for_rect(
                w["x_pct"], w["y_pct"], w["w_pct"], w["h_pct"], lines, allow_right=True
            )
            match_val = w["on_state"]
            if not match_val or match_val.lower() in ("yes", "on", "true", "1", "choice1", "choice2"):
                if opt_line and len(opt_line["text"]) <= 35:
                    match_val = opt_line["text"].strip(":. ")
            match_val = match_val or f"Option {idx + 1}"
            mappings.append(
                {
                    "type": "checkbox",
                    "field_key": f_key,
                    "label": f_label,
                    "question_text": q_text,
                    "section": section,
                    "match_value": match_val,
                    "x_pct": w["cx_pct"],
                    "y_pct": w["cy_pct"],
                    "width_pct": None,
                    "height_pct": None,
                    "qx_pct": q_line["x_pct"] if q_line else None,
                    "qy_pct": q_line["y_pct"] if q_line else None,
                    "qw_pct": q_line["w_pct"] if q_line else None,
                    "qh_pct": q_line["h_pct"] if q_line else None,
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.96,
                    "detection_source": "acroform",
                    "acroform_field_name": w["field_name"] or None,
                }
            )
            continue

        nearest_line = _find_nearest_label_for_rect(
            w["x_pct"],
            w["y_pct"],
            w["w_pct"],
            w["h_pct"],
            lines,
            allow_right=(kind == "checkbox"),
        )
        if _is_cryptic_widget_name(raw_name) and nearest_line:
            q_text = nearest_line["text"]
            f_key, f_label = normalize_label_to_key_and_label(q_text)
        else:
            q_text = nearest_line["text"] if nearest_line else raw_name
            f_key, f_label = normalize_label_to_key_and_label(raw_name)

        if kind == "checkbox":
            match_val = w["on_state"] or "Yes"
            if match_val.lower() in ("off", "yes", "on", "true", "1"):
                match_val = "Yes"
            mappings.append(
                {
                    "type": "checkbox",
                    "field_key": f_key,
                    "label": f_label,
                    "question_text": q_text,
                    "section": section,
                    "match_value": match_val,
                    "x_pct": w["cx_pct"],
                    "y_pct": w["cy_pct"],
                    "width_pct": None,
                    "height_pct": None,
                    "qx_pct": nearest_line["x_pct"] if nearest_line else None,
                    "qy_pct": nearest_line["y_pct"] if nearest_line else None,
                    "qw_pct": nearest_line["w_pct"] if nearest_line else None,
                    "qh_pct": nearest_line["h_pct"] if nearest_line else None,
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.96,
                    "detection_source": "acroform",
                    "acroform_field_name": w["field_name"] or None,
                }
            )
        elif kind == "signature" or SIGNATURE_KEYWORDS.search(f_label):
            is_witness = "witness" in f_key or "witness" in q_text.lower()
            sig_key = "witness_signature" if is_witness else (f_key if "sign" in f_key else "applicant_signature")
            mappings.append(
                {
                    "type": "image",
                    "field_key": sig_key,
                    "label": "Witness signature" if is_witness else (f_label if "sign" in f_label.lower() else "Signature"),
                    "question_text": q_text,
                    "section": section,
                    "match_value": None,
                    "x_pct": w["x_pct"],
                    "y_pct": w["y_pct"],
                    "width_pct": max(0.08, w["w_pct"]),
                    "height_pct": max(0.035, w["h_pct"]),
                    "qx_pct": nearest_line["x_pct"] if nearest_line else None,
                    "qy_pct": nearest_line["y_pct"] if nearest_line else None,
                    "qw_pct": nearest_line["w_pct"] if nearest_line else None,
                    "qh_pct": nearest_line["h_pct"] if nearest_line else None,
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.97,
                    "detection_source": "acroform",
                    "acroform_field_name": w["field_name"] or None,
                }
            )
        else:
            mapped_type = "multiline" if kind == "multiline" else "text"
            mappings.append(
                {
                    "type": mapped_type,
                    "field_key": f_key,
                    "label": f_label,
                    "question_text": q_text,
                    "section": section,
                    "match_value": None,
                    "x_pct": w["x_pct"],
                    "y_pct": w["y_pct"],
                    "width_pct": max(0.04, w["w_pct"]),
                    "height_pct": max(0.018, w["h_pct"]),
                    "qx_pct": nearest_line["x_pct"] if nearest_line else None,
                    "qy_pct": nearest_line["y_pct"] if nearest_line else None,
                    "qw_pct": nearest_line["w_pct"] if nearest_line else None,
                    "qh_pct": nearest_line["h_pct"] if nearest_line else None,
                    "page_number": page_num,
                    "font_size": 10.0,
                    "align": "left",
                    "confidence": 0.97,
                    "detection_source": "acroform",
                    "acroform_field_name": w["field_name"] or None,
                }
            )

    return mappings


# =============================================================================
# STAGE 4: UPGRADED OFFLINE VECTOR-GEOMETRY Q->A ENGINE (NO API KEY REQUIRED)
# =============================================================================
def _rect_contains_text_with_indices(
    box: Dict[str, Any], lines: List[Dict[str, Any]]
) -> List[Tuple[int, Dict[str, Any]]]:
    """Returns (index, line_dict) pairs whose center falls inside the given vector box."""
    bx0, by0 = box["x_pct"] - 0.004, box["y_pct"] - 0.004
    bx1, by1 = box["x_pct"] + box["w_pct"] + 0.004, box["y_pct"] + box["h_pct"] + 0.004
    inside: List[Tuple[int, Dict[str, Any]]] = []
    for idx_l, ln in enumerate(lines):
        lcx = ln["x_pct"] + ln["w_pct"] * 0.5
        lcy = ln["y_pct"] + ln["h_pct"] * 0.5
        if bx0 <= lcx <= bx1 and by0 <= lcy <= by1:
            inside.append((idx_l, ln))
    return inside


def _rect_contains_text(box: Dict[str, Any], lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns text lines whose center falls inside the given vector box."""
    return [ln for _, ln in _rect_contains_text_with_indices(box, lines)]


PAREN_CB_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9\-\s/:?]{0,36}?)\s*([\(\[]\s*[\)\]]|[☐□])"
)


def _extract_inline_paren_checkboxes(
    ln: Dict[str, Any],
    page_num: int,
    sections: List[Dict[str, Any]],
    add_mapping_fn: Any,
    context_label: Optional[str] = None,
    context_q_src: Optional[Dict[str, Any]] = None,
    container_right_pct: float = 0.92,
) -> bool:
    """
    Detects parenthetical/bracket blank checkboxes such as:
      'None(  ) Beginner(  ) Intermediate(  ) Advanced(  )'
      'Yes (  ) No (  ) Why:'
    and emits grouped checkbox mappings + any trailing inline text prompt.
    Returns True if checkboxes were found and emitted.
    """
    txt = ln["text"].strip()
    matches = list(PAREN_CB_RE.finditer(txt))
    if not matches:
        return False

    total_len = max(1, len(txt))
    inline_prompt: Optional[str] = None
    first_opt_raw = matches[0].group(1).strip()

    # Handle lines like "Gender: Male (  ) Female (  )"
    if ":" in first_opt_raw or "?" in first_opt_raw:
        sep_match = re.match(r"^(.*[:?])\s+([A-Za-z0-9\-/\s]+)$", first_opt_raw)
        if sep_match:
            inline_prompt = sep_match.group(1).strip()

    q_text = context_label or inline_prompt or f"Choice (Page {page_num})"
    fk, fl = normalize_label_to_key_and_label(q_text)
    if not context_label and not inline_prompt:
        fk = f"choice_p{page_num}_r{int(round(ln['y_pct'] * 100))}"
        fl = "Choice"

    q_src = context_q_src or ln

    for idx_m, m in enumerate(matches):
        opt_raw = m.group(1).strip()
        if idx_m == 0 and inline_prompt and (":" in opt_raw or "?" in opt_raw):
            sep_match = re.match(r"^(.*[:?])\s+([A-Za-z0-9\-/\s]+)$", opt_raw)
            if sep_match:
                opt_raw = sep_match.group(2).strip()

        opt_clean = re.sub(r"^[\s,;:\-]+", "", opt_raw).strip()
        if not opt_clean:
            continue

        slot_mid = (m.start(2) + m.end(2)) * 0.5 / total_len
        cb_x = round(max(0.01, min(0.98, ln["x_pct"] + ln["w_pct"] * slot_mid)), 4)
        cb_y = round(max(0.01, min(0.98, ln["y_pct"] + ln["h_pct"] * 0.5)), 4)

        add_mapping_fn(
            {
                "type": "checkbox",
                "field_key": fk,
                "label": fl,
                "question_text": q_text,
                "section": _current_section_for_y(cb_y, sections),
                "match_value": opt_clean[:48],
                "x_pct": cb_x,
                "y_pct": cb_y,
                "width_pct": None,
                "height_pct": None,
                "qx_pct": q_src["x_pct"] if q_src else None,
                "qy_pct": q_src["y_pct"] if q_src else None,
                "qw_pct": q_src["w_pct"] if q_src else None,
                "qh_pct": q_src["h_pct"] if q_src else None,
                "page_number": page_num,
                "font_size": None,
                "align": "left",
                "confidence": 0.84,
                "detection_source": "geometry",
                "acroform_field_name": None,
            },
            spot_x=cb_x,
            spot_y=cb_y,
        )

    # Check if a follow-up text prompt sits after the last checkbox (e.g. "Why:", "What/Where?", "NYSC Date:")
    tail = txt[matches[-1].end() :].strip(" .,-")
    if len(tail) >= 2 and re.search(r"[A-Za-z]", tail):
        tail_clean = tail.rstrip(":? ").strip()
        if tail_clean:
            tfk, tfl = normalize_label_to_key_and_label(tail_clean)
            if tfk in ("why", "comment", "what_where", "details") and fl and fl != "Choice":
                short_parent = fl[:28].rstrip()
                tfl = f"{short_parent} ({tfl})"
                tfk = f"{fk}_{tfk}"[:48].rstrip("_")

            start_x = round(min(container_right_pct - 0.05, ln["x_pct"] + ln["w_pct"] + 0.008), 4)
            avail_w = round(max(0.08, container_right_pct - start_x), 4)
            bh = round(max(0.020, min(0.032, ln["h_pct"] * 1.45)), 4)
            by = round(max(0.005, ln["y_pct"] - 0.002), 4)
            add_mapping_fn(
                {
                    "type": "text",
                    "field_key": tfk,
                    "label": tfl,
                    "question_text": tail,
                    "section": _current_section_for_y(by, sections),
                    "match_value": None,
                    "x_pct": start_x,
                    "y_pct": by,
                    "width_pct": avail_w,
                    "height_pct": bh,
                    "qx_pct": ln["x_pct"],
                    "qy_pct": ln["y_pct"],
                    "qw_pct": ln["w_pct"],
                    "qh_pct": ln["h_pct"],
                    "page_number": page_num,
                    "font_size": 9.5,
                    "align": "left",
                    "confidence": 0.78,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                }
            )

    return True


def _analyze_page_geometry_offline(page_scrape: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Universal offline Q->A detector combining scraped text lines with PyMuPDF vector drawings:
      1. Large photo / stamp / signature boxes
      2. Universal vector checkboxes/radios (left OR right of option labels, grouped by row/prompt)
      3. Table cells (empty value cell to the right of a label cell, or below a header row)
      4. Bordered input boxes (empty boxes with label above/left, or small label inside top-left)
      5. Vector underlines paired with left/below/above prompts
      6. Inline text fill-in-the-blanks ("I, ________, residing at ________" or "Label: ____")
    """
    page_num = page_scrape["page_number"]
    lines = page_scrape.get("lines", [])
    sections = page_scrape.get("sections", [])
    geom = page_scrape.get("geometry", {})

    underlines = geom.get("underlines", [])
    checkbox_shapes = geom.get("checkbox_candidates", [])
    text_boxes = geom.get("text_boxes", [])
    large_boxes = geom.get("large_boxes", [])
    table_cells = geom.get("table_cells", [])

    mappings: List[Dict[str, Any]] = []
    seen_spots: List[Tuple[float, float]] = []
    used_line_indices: set[int] = set()

    def is_spot_taken(xp: float, yp: float, tol_x: float = 0.032, tol_y: float = 0.016) -> bool:
        for sx, sy in seen_spots:
            if abs(sx - xp) < tol_x and abs(sy - yp) < tol_y:
                return True
        return False

    def add_mapping(m: Dict[str, Any], spot_x: Optional[float] = None, spot_y: Optional[float] = None) -> None:
        sx = spot_x if spot_x is not None else m["x_pct"]
        sy = spot_y if spot_y is not None else m["y_pct"]
        if not is_spot_taken(sx, sy):
            mappings.append(m)
            seen_spots.append((sx, sy))

    # -------------------------------------------------------------------------
    # 1. Detect Photo / Stamp Frames from large_boxes + text cues
    # -------------------------------------------------------------------------
    for lb in large_boxes:
        inside = _rect_contains_text(lb, lines)
        inside_txt = " ".join(x["text"] for x in inside).strip()
        nearby = _find_nearest_label_for_rect(lb["x_pct"], lb["y_pct"], lb["w_pct"], lb["h_pct"], lines)
        combined = f"{inside_txt} {nearby['text'] if nearby else ''}".strip()

        if PHOTO_KEYWORDS.search(combined):
            q_src = inside[0] if inside else nearby
            add_mapping(
                {
                    "type": "image",
                    "field_key": "profile_photo",
                    "label": "Profile / ID photo",
                    "question_text": (q_src["text"] if q_src else "Profile / ID photo"),
                    "section": _current_section_for_y(lb["y_pct"], sections),
                    "match_value": None,
                    "x_pct": lb["x_pct"],
                    "y_pct": lb["y_pct"],
                    "width_pct": lb["w_pct"],
                    "height_pct": lb["h_pct"],
                    "qx_pct": q_src["x_pct"] if q_src else lb["x_pct"],
                    "qy_pct": q_src["y_pct"] if q_src else lb["y_pct"],
                    "qw_pct": q_src["w_pct"] if q_src else lb["w_pct"],
                    "qh_pct": q_src["h_pct"] if q_src else lb["h_pct"],
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.90,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                }
            )
            for idx_l, ln in enumerate(lines):
                if ln in inside:
                    used_line_indices.add(idx_l)
        elif STAMP_KEYWORDS.search(combined):
            q_src = inside[0] if inside else nearby
            add_mapping(
                {
                    "type": "image",
                    "field_key": "company_stamp",
                    "label": "Official stamp / Seal",
                    "question_text": (q_src["text"] if q_src else "Official stamp"),
                    "section": _current_section_for_y(lb["y_pct"], sections),
                    "match_value": None,
                    "x_pct": lb["x_pct"],
                    "y_pct": lb["y_pct"],
                    "width_pct": lb["w_pct"],
                    "height_pct": lb["h_pct"],
                    "qx_pct": q_src["x_pct"] if q_src else lb["x_pct"],
                    "qy_pct": q_src["y_pct"] if q_src else lb["y_pct"],
                    "qw_pct": q_src["w_pct"] if q_src else lb["w_pct"],
                    "qh_pct": q_src["h_pct"] if q_src else lb["h_pct"],
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.88,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                }
            )
            for idx_l, ln in enumerate(lines):
                if ln in inside:
                    used_line_indices.add(idx_l)

    # -------------------------------------------------------------------------
    # 2. Universal Vector Checkbox / Radio Detection (Left OR Right of Option)
    # -------------------------------------------------------------------------
    cb_rows: List[List[Dict[str, Any]]] = []
    for cb in sorted(checkbox_shapes, key=lambda c: (round(c["cy_pct"] / 0.015), c["cx_pct"])):
        placed = False
        for row in cb_rows:
            if abs(cb["cy_pct"] - row[0]["cy_pct"]) <= 0.018:
                row.append(cb)
                placed = True
                break
        if not placed:
            cb_rows.append([cb])

    for cb_row in cb_rows:
        cb_row.sort(key=lambda c: c["cx_pct"])
        row_y = sum(c["cy_pct"] for c in cb_row) / len(cb_row)
        # All text lines on the same horizontal band as this checkbox row
        band_lines = [
            (i, ln)
            for i, ln in enumerate(lines)
            if abs((ln["y_pct"] + ln["h_pct"] * 0.5) - row_y) <= 0.018
        ]
        band_lines.sort(key=lambda pair: pair[1]["x_pct"])

        # Find a question/category prompt at the left of the row or directly above the first checkbox
        row_prompt_line = None
        first_cb_x = cb_row[0]["x_pct"]
        for i, ln in band_lines:
            if ln["x_pct"] + ln["w_pct"] <= first_cb_x + 0.01 and (
                ln["text"].rstrip().endswith(":") or ln["text"].rstrip().endswith("?") or len(cb_row) >= 2
            ):
                # Prefer the leftmost label ending in ":" or "?" as the category prompt
                if ln["text"].rstrip().endswith((":", "?")):
                    row_prompt_line = ln
                    used_line_indices.add(i)
                    break

        if not row_prompt_line:
            above_q = _find_nearest_label_for_rect(
                cb_row[0]["x_pct"], cb_row[0]["y_pct"], 0.3, cb_row[0]["h_pct"], lines
            )
            if above_q and above_q["y_pct"] < row_y - 0.012:
                row_prompt_line = above_q

        if row_prompt_line:
            group_key, group_label = normalize_label_to_key_and_label(row_prompt_line["text"])
            group_q_text = row_prompt_line["text"]
        else:
            group_key, group_label, group_q_text = None, None, None

        for cb_idx, cb in enumerate(cb_row):
            # Pair this checkbox with the closest option text to its RIGHT or LEFT (not the category prompt)
            best_opt = None
            best_opt_idx = None
            best_dist = 0.14
            for i, ln in band_lines:
                if row_prompt_line and ln is row_prompt_line:
                    continue
                lx0 = ln["x_pct"]
                lx1 = lx0 + ln["w_pct"]
                # Right of box: "[ ] Option"
                r_gap = lx0 - (cb["x_pct"] + cb["w_pct"])
                # Left of box: "Option [ ]"
                l_gap = cb["x_pct"] - lx1
                dist = None
                if -0.005 <= r_gap <= best_dist:
                    dist = max(0.0, r_gap)
                elif -0.005 <= l_gap <= best_dist:
                    dist = max(0.0, l_gap) + 0.003
                if dist is not None and dist < best_dist:
                    best_dist = dist
                    best_opt = ln
                    best_opt_idx = i

            opt_text = best_opt["text"].strip(" :.,[]☐□") if best_opt else f"Option {cb_idx + 1}"
            if best_opt_idx is not None:
                used_line_indices.add(best_opt_idx)

            if len(cb_row) == 1 and not group_key:
                # Standalone single checkbox (e.g. "[ ] I agree to the terms")
                fk, fl = normalize_label_to_key_and_label(opt_text)
                mv = "Yes"
                qt = opt_text
                q_src = best_opt
            else:
                fk = group_key or f"choice_p{page_num}_r{int(round(row_y * 100))}"
                fl = group_label or humanize_key(fk)
                mv = opt_text[:48] or "Yes"
                qt = group_q_text or fl
                q_src = row_prompt_line or best_opt

            add_mapping(
                {
                    "type": "checkbox",
                    "field_key": fk,
                    "label": fl,
                    "question_text": qt,
                    "section": _current_section_for_y(cb["cy_pct"], sections),
                    "match_value": mv,
                    "x_pct": cb["cx_pct"],
                    "y_pct": cb["cy_pct"],
                    "width_pct": None,
                    "height_pct": None,
                    "qx_pct": q_src["x_pct"] if q_src else None,
                    "qy_pct": q_src["y_pct"] if q_src else None,
                    "qw_pct": q_src["w_pct"] if q_src else None,
                    "qh_pct": q_src["h_pct"] if q_src else None,
                    "page_number": page_num,
                    "font_size": None,
                    "align": "left",
                    "confidence": 0.86,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                },
                spot_x=cb["cx_pct"],
                spot_y=cb["cy_pct"],
            )

    # -------------------------------------------------------------------------
    # 3. Table Cells: 2-Column Label->Value Tables & Header-Row Multi-Row Tables
    # -------------------------------------------------------------------------
    if table_cells:
        by_row: Dict[int, List[Dict[str, Any]]] = {}
        for cell in table_cells:
            by_row.setdefault(cell["row_idx"], []).append(cell)
        for r_cells in by_row.values():
            r_cells.sort(key=lambda c: c["col_idx"])

        # Identify column headers from the first populated row
        col_headers: Dict[int, str] = {}
        sorted_r_indices = sorted(by_row.keys())
        if sorted_r_indices:
            first_row = by_row[sorted_r_indices[0]]
            filled_in_first = [(_rect_contains_text(c, lines), c) for c in first_row]
            if len(first_row) >= 2 and all(len(txts) > 0 for txts, _ in filled_in_first):
                # Looks like a header row if row 1 has empty cells
                if len(sorted_r_indices) >= 2:
                    second_row = by_row[sorted_r_indices[1]]
                    if any(len(_rect_contains_text(c, lines)) == 0 for c in second_row):
                        for txts, c in filled_in_first:
                            col_headers[c["col_idx"]] = " ".join(t["text"] for t in txts).strip()

        for r_idx in sorted_r_indices:
            r_cells = by_row[r_idx]
            if r_idx == sorted_r_indices[0] and col_headers:
                for hdr_cell in r_cells:
                    for idx_l, _ in _rect_contains_text_with_indices(hdr_cell, lines):
                        used_line_indices.add(idx_l)
                continue
            for c_pos, cell in enumerate(r_cells):
                inside_pairs = _rect_contains_text_with_indices(cell, lines)
                inside = [ln for _, ln in inside_pairs]
                for idx_l, _ in inside_pairs:
                    used_line_indices.add(idx_l)

                if inside:
                    # Check if this populated right-hand cell contains inline parenthetical checkboxes
                    left_label_text = None
                    left_q_src = None
                    if c_pos > 0:
                        left_pairs = _rect_contains_text_with_indices(r_cells[c_pos - 1], lines)
                        if left_pairs:
                            left_label_text = " ".join(ln["text"] for _, ln in left_pairs).strip()
                            left_q_src = left_pairs[0][1]
                            for idx_l, _ in left_pairs:
                                used_line_indices.add(idx_l)

                    found_cb_in_cell = False
                    cell_right_limit = min(0.95, cell["x_pct"] + cell["w_pct"] - 0.004)
                    for ln in inside:
                        if PAREN_CB_RE.search(ln["text"]):
                            if _extract_inline_paren_checkboxes(
                                ln=ln,
                                page_num=page_num,
                                sections=sections,
                                add_mapping_fn=add_mapping,
                                context_label=left_label_text,
                                context_q_src=left_q_src,
                                container_right_pct=cell_right_limit,
                            ):
                                found_cb_in_cell = True

                    if found_cb_in_cell:
                        continue

                    # Check if cell has a tiny label in its top-left corner and blank space beneath
                    if len(inside) == 1 and cell["h_pct"] >= 0.036 and inside[0]["y_pct"] <= cell["y_pct"] + cell["h_pct"] * 0.35:
                        lbl_ln = inside[0]
                        if not IGNORE_LINE_PATTERNS.search(lbl_ln["text"]) and len(lbl_ln["text"]) <= 50:
                            fk, fl = normalize_label_to_key_and_label(lbl_ln["text"])
                            ans_y = round(lbl_ln["y_pct"] + lbl_ln["h_pct"] + 0.003, 4)
                            ans_h = round(max(0.018, (cell["y_pct"] + cell["h_pct"]) - ans_y - 0.003), 4)
                            add_mapping(
                                {
                                    "type": "multiline" if ans_h >= 0.055 else "text",
                                    "field_key": fk,
                                    "label": fl,
                                    "question_text": lbl_ln["text"],
                                    "section": _current_section_for_y(cell["y_pct"], sections),
                                    "match_value": None,
                                    "x_pct": round(cell["x_pct"] + 0.004, 4),
                                    "y_pct": ans_y,
                                    "width_pct": round(max(0.03, cell["w_pct"] - 0.008), 4),
                                    "height_pct": ans_h,
                                    "qx_pct": lbl_ln["x_pct"],
                                    "qy_pct": lbl_ln["y_pct"],
                                    "qw_pct": lbl_ln["w_pct"],
                                    "qh_pct": lbl_ln["h_pct"],
                                    "page_number": page_num,
                                    "font_size": 10.0,
                                    "align": "left",
                                    "confidence": 0.85,
                                    "detection_source": "geometry",
                                    "acroform_field_name": None,
                                }
                            )
                    continue

                # Cell is EMPTY -> look left in the same row, or up to col_headers
                label_text = None
                q_src = None
                if c_pos > 0:
                    left_pairs = _rect_contains_text_with_indices(r_cells[c_pos - 1], lines)
                    if left_pairs:
                        label_text = " ".join(ln["text"] for _, ln in left_pairs).strip()
                        q_src = left_pairs[0][1]
                        for idx_l, _ in left_pairs:
                            used_line_indices.add(idx_l)
                if not label_text and cell["col_idx"] in col_headers:
                    hdr = col_headers[cell["col_idx"]]
                    label_text = f"{hdr} (Row {r_idx})"

                if label_text and not IGNORE_LINE_PATTERNS.search(label_text):
                    fk, fl = normalize_label_to_key_and_label(label_text)
                    is_sig = bool(SIGNATURE_KEYWORDS.search(label_text))
                    add_mapping(
                        {
                            "type": "image" if is_sig else ("multiline" if cell["h_pct"] >= 0.06 else "text"),
                            "field_key": "applicant_signature" if is_sig else fk,
                            "label": "Signature" if is_sig else fl,
                            "question_text": label_text,
                            "section": _current_section_for_y(cell["y_pct"], sections),
                            "match_value": None,
                            "x_pct": round(cell["x_pct"] + 0.004, 4),
                            "y_pct": round(cell["y_pct"] + 0.003, 4),
                            "width_pct": round(max(0.03, cell["w_pct"] - 0.008), 4),
                            "height_pct": round(max(0.018, cell["h_pct"] - 0.006), 4),
                            "qx_pct": q_src["x_pct"] if q_src else None,
                            "qy_pct": q_src["y_pct"] if q_src else None,
                            "qw_pct": q_src["w_pct"] if q_src else None,
                            "qh_pct": q_src["h_pct"] if q_src else None,
                            "page_number": page_num,
                            "font_size": None if is_sig else 10.0,
                            "align": "left",
                            "confidence": 0.86,
                            "detection_source": "geometry",
                            "acroform_field_name": None,
                        }
                    )

    # -------------------------------------------------------------------------
    # 4. Standalone Bordered Input Boxes (Label Above, Left, or Inside Top-Left)
    # -------------------------------------------------------------------------
    for tb in text_boxes:
        if is_spot_taken(tb["x_pct"], tb["y_pct"], tol_x=0.025, tol_y=0.015):
            continue
        inside = _rect_contains_text(tb, lines)
        if len(inside) >= 2:
            # Probably a decorative text callout, not a blank input
            continue
        if len(inside) == 1:
            lbl_ln = inside[0]
            # Label inside top-left of box (e.g., "Email Address" in small font at top of box)
            if tb["h_pct"] >= 0.034 and lbl_ln["y_pct"] <= tb["y_pct"] + tb["h_pct"] * 0.38 and len(lbl_ln["text"]) <= 55:
                if not IGNORE_LINE_PATTERNS.search(lbl_ln["text"]):
                    fk, fl = normalize_label_to_key_and_label(lbl_ln["text"])
                    ans_y = round(lbl_ln["y_pct"] + lbl_ln["h_pct"] + 0.003, 4)
                    ans_h = round(max(0.018, (tb["y_pct"] + tb["h_pct"]) - ans_y - 0.003), 4)
                    add_mapping(
                        {
                            "type": "multiline" if ans_h >= 0.055 else "text",
                            "field_key": fk,
                            "label": fl,
                            "question_text": lbl_ln["text"],
                            "section": _current_section_for_y(tb["y_pct"], sections),
                            "match_value": None,
                            "x_pct": round(tb["x_pct"] + 0.004, 4),
                            "y_pct": ans_y,
                            "width_pct": round(max(0.04, tb["w_pct"] - 0.008), 4),
                            "height_pct": ans_h,
                            "qx_pct": lbl_ln["x_pct"],
                            "qy_pct": lbl_ln["y_pct"],
                            "qw_pct": lbl_ln["w_pct"],
                            "qh_pct": lbl_ln["h_pct"],
                            "page_number": page_num,
                            "font_size": 10.0,
                            "align": "left",
                            "confidence": 0.84,
                            "detection_source": "geometry",
                            "acroform_field_name": None,
                        }
                    )
            continue

        # Completely EMPTY bordered box -> find label to the left or directly above
        q_line = _find_nearest_label_for_rect(tb["x_pct"], tb["y_pct"], tb["w_pct"], tb["h_pct"], lines)
        if q_line:
            txt = q_line["text"]
            is_sig = bool(SIGNATURE_KEYWORDS.search(txt))
            is_photo = bool(PHOTO_KEYWORDS.search(txt))
            fk, fl = normalize_label_to_key_and_label(txt)
            if is_photo:
                m_type, fk, fl = "image", "profile_photo", "Profile / ID photo"
            elif is_sig:
                is_w = "witness" in txt.lower()
                m_type = "image"
                fk = "witness_signature" if is_w else "applicant_signature"
                fl = "Witness signature" if is_w else "Signature"
            else:
                m_type = "multiline" if tb["h_pct"] >= 0.055 else "text"

            add_mapping(
                {
                    "type": m_type,
                    "field_key": fk,
                    "label": fl,
                    "question_text": txt,
                    "section": _current_section_for_y(tb["y_pct"], sections),
                    "match_value": None,
                    "x_pct": round(tb["x_pct"] + 0.004, 4),
                    "y_pct": round(tb["y_pct"] + 0.003, 4),
                    "width_pct": round(max(0.04, tb["w_pct"] - 0.008), 4),
                    "height_pct": round(max(0.018, tb["h_pct"] - 0.006), 4),
                    "qx_pct": q_line["x_pct"],
                    "qy_pct": q_line["y_pct"],
                    "qw_pct": q_line["w_pct"],
                    "qh_pct": q_line["h_pct"],
                    "page_number": page_num,
                    "font_size": None if m_type == "image" else 10.0,
                    "align": "left",
                    "confidence": 0.85,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                }
            )

    # -------------------------------------------------------------------------
    # 5. Vector Underlines Paired with Adjacent Prompts (Left or Directly Below)
    # -------------------------------------------------------------------------
    for ul in underlines:
        ul_x = ul["x_pct"]
        ul_y = ul["y_pct"]
        ul_w = ul["w_pct"]
        if ul_w < 0.05:
            continue

        # Check for label directly to the LEFT on the same baseline
        best_left = None
        best_left_idx = None
        best_left_gap = 0.16
        for idx_l, ln in enumerate(lines):
            if idx_l in used_line_indices or IGNORE_LINE_PATTERNS.search(ln["text"]):
                continue
            ly_bot = ln["y_pct"] + ln["h_pct"]
            lx1 = ln["x_pct"] + ln["w_pct"]
            if abs(ly_bot - ul_y) <= 0.016:
                gap = ul_x - lx1
                if -0.015 <= gap <= best_left_gap:
                    best_left_gap = gap
                    best_left = ln
                    best_left_idx = idx_l

        # Or check for label directly BELOW the underline (classic signature / date line!)
        best_below = None
        best_below_idx = None
        if not best_left:
            for idx_l, ln in enumerate(lines):
                if idx_l in used_line_indices or IGNORE_LINE_PATTERNS.search(ln["text"]):
                    continue
                v_gap = ln["y_pct"] - ul_y
                if 0.0 <= v_gap <= 0.024:
                    x_overlap = min(ul_x + ul_w, ln["x_pct"] + ln["w_pct"]) - max(ul_x, ln["x_pct"])
                    if x_overlap > 0.01 or abs(ln["x_pct"] - ul_x) <= 0.04:
                        best_below = ln
                        best_below_idx = idx_l
                        break

        q_line = best_left or best_below
        q_idx = best_left_idx if best_left else best_below_idx
        if not q_line or len(q_line["text"]) > 110:
            continue

        txt = q_line["text"]
        is_sig = bool(SIGNATURE_KEYWORDS.search(txt))
        is_photo = bool(PHOTO_KEYWORDS.search(txt))
        if is_photo:
            continue

        fk, fl = normalize_label_to_key_and_label(txt)
        if is_sig:
            is_w = "witness" in txt.lower()
            m_type = "image"
            fk = "witness_signature" if is_w else "applicant_signature"
            fl = "Witness signature" if is_w else "Signature"
            box_h = 0.042
            box_y = max(0.005, ul_y - box_h + 0.003)
        else:
            m_type = "text"
            box_h = max(0.022, min(0.032, q_line["h_pct"] * 1.45))
            box_y = max(0.005, ul_y - box_h + 0.003)

        add_mapping(
            {
                "type": m_type,
                "field_key": fk,
                "label": fl,
                "question_text": txt,
                "section": _current_section_for_y(box_y, sections),
                "match_value": None,
                "x_pct": round(ul_x + 0.003, 4),
                "y_pct": round(box_y, 4),
                "width_pct": round(max(0.04, ul_w - 0.006), 4),
                "height_pct": round(box_h, 4),
                "qx_pct": q_line["x_pct"],
                "qy_pct": q_line["y_pct"],
                "qw_pct": q_line["w_pct"],
                "qh_pct": q_line["h_pct"],
                "page_number": page_num,
                "font_size": None if m_type == "image" else 10.0,
                "align": "left",
                "confidence": 0.84,
                "detection_source": "geometry",
                "acroform_field_name": None,
            }
        )
        if q_idx is not None:
            used_line_indices.add(q_idx)

    # -------------------------------------------------------------------------
    # 6. Inline Fill-in-the-Blank & Colon-Terminated Text Prompts
    # -------------------------------------------------------------------------
    # Group remaining lines into horizontal rows
    rem_rows: List[List[Tuple[int, Dict[str, Any]]]] = []
    for idx_l, ln in enumerate(lines):
        if idx_l in used_line_indices:
            continue
        placed = False
        for r in rem_rows:
            if abs(ln["y_pct"] - r[0][1]["y_pct"]) <= 0.011:
                r.append((idx_l, ln))
                placed = True
                break
        if not placed:
            rem_rows.append([(idx_l, ln)])

    for row in rem_rows:
        row.sort(key=lambda pair: pair[1]["x_pct"])
        for pos, (idx_l, ln) in enumerate(row):
            raw_txt = ln["text"].strip()
            if len(raw_txt) < 2 or len(raw_txt) > 150 or IGNORE_LINE_PATTERNS.search(raw_txt):
                continue

            # 6.0 Standalone line containing parenthetical/bracket blank checkboxes
            if PAREN_CB_RE.search(raw_txt):
                above_prompt = None
                for cand_ln in reversed(lines):
                    if cand_ln["y_pct"] < ln["y_pct"] - 0.005 and (ln["y_pct"] - cand_ln["y_pct"]) <= 0.04:
                        if not PAREN_CB_RE.search(cand_ln["text"]) and not IGNORE_LINE_PATTERNS.search(cand_ln["text"]):
                            above_prompt = cand_ln
                            break
                if _extract_inline_paren_checkboxes(
                    ln=ln,
                    page_num=page_num,
                    sections=sections,
                    add_mapping_fn=add_mapping,
                    context_label=above_prompt["text"] if above_prompt else None,
                    context_q_src=above_prompt,
                    container_right_pct=0.92,
                ):
                    continue

            # 6a. Multiple or single inline underscore/dot blanks: e.g. "I, __________, residing at __________"
            blank_matches = list(re.finditer(r"[_]{4,}|[\.]{5,}", raw_txt))
            if blank_matches:
                total_len = max(1, len(raw_txt))
                prev_end = 0
                for b_idx, bm in enumerate(blank_matches):
                    prefix = raw_txt[prev_end : bm.start()].strip(" ,;:-")
                    prev_end = bm.end()
                    if not prefix:
                        continue
                    # Take the trailing clause before the blank as the question prompt
                    clause = re.split(r"[,;]", prefix)[-1].strip()
                    if not clause or len(clause) < 2:
                        clause = prefix
                    fk, fl = normalize_label_to_key_and_label(clause)
                    is_sig = bool(SIGNATURE_KEYWORDS.search(clause))

                    bx = round(ln["x_pct"] + ln["w_pct"] * (bm.start() / total_len), 4)
                    bw = round(max(0.06, ln["w_pct"] * ((bm.end() - bm.start()) / total_len)), 4)
                    bh = 0.040 if is_sig else round(max(0.022, min(0.036, ln["h_pct"] * 1.45)), 4)
                    by = round(max(0.005, ln["y_pct"] - (0.018 if is_sig else 0.003)), 4)

                    add_mapping(
                        {
                            "type": "image" if is_sig else "text",
                            "field_key": "applicant_signature" if is_sig else fk,
                            "label": "Signature" if is_sig else fl,
                            "question_text": clause,
                            "section": _current_section_for_y(by, sections),
                            "match_value": None,
                            "x_pct": bx,
                            "y_pct": by,
                            "width_pct": min(1.0 - bx, bw),
                            "height_pct": bh,
                            "qx_pct": ln["x_pct"],
                            "qy_pct": ln["y_pct"],
                            "qw_pct": round(ln["w_pct"] * (bm.start() / total_len), 4),
                            "qh_pct": ln["h_pct"],
                            "page_number": page_num,
                            "font_size": None if is_sig else 10.0,
                            "align": "left",
                            "confidence": 0.78,
                            "detection_source": "geometry",
                            "acroform_field_name": None,
                        }
                    )
                continue

            # 6b. Colon/question-mark prompt with blank space to its right
            has_prompt_punct = raw_txt.endswith((":", "?"))
            clean_cand = re.sub(r"[\s\:\?\.\_\-\*\/]+$", "", raw_txt).strip()
            is_known = any(re.match(pat, clean_cand.lower(), re.IGNORECASE) for pat, _, _ in RAW_LABEL_SYNONYMS)
            if not (has_prompt_punct or is_known) or len(clean_cand) < 2 or len(clean_cand) > 75:
                continue
            if re.match(r"^[\d\W]+$", clean_cand):
                continue

            # Ensure there actually is blank horizontal space to the right
            start_x = round(min(0.90, ln["x_pct"] + ln["w_pct"] + 0.012), 4)
            if pos + 1 < len(row):
                next_x = row[pos + 1][1]["x_pct"] - 0.01
                end_x = min(0.94, next_x)
            else:
                end_x = 0.92
            avail_w = end_x - start_x
            if avail_w < 0.06:
                continue

            is_sig = bool(SIGNATURE_KEYWORDS.search(clean_cand))
            is_photo = bool(PHOTO_KEYWORDS.search(clean_cand))
            if is_photo:
                continue

            fk, fl = normalize_label_to_key_and_label(clean_cand)
            bh = 0.042 if is_sig else round(max(0.022, min(0.036, ln["h_pct"] * 1.45)), 4)
            by = round(max(0.005, ln["y_pct"] - (0.015 if is_sig else 0.002)), 4)

            add_mapping(
                {
                    "type": "image" if is_sig else "text",
                    "field_key": "applicant_signature" if is_sig else fk,
                    "label": "Signature" if is_sig else fl,
                    "question_text": raw_txt,
                    "section": _current_section_for_y(by, sections),
                    "match_value": None,
                    "x_pct": start_x,
                    "y_pct": by,
                    "width_pct": round(min(0.84, avail_w), 4),
                    "height_pct": bh,
                    "qx_pct": ln["x_pct"],
                    "qy_pct": ln["y_pct"],
                    "qw_pct": ln["w_pct"],
                    "qh_pct": ln["h_pct"],
                    "page_number": page_num,
                    "font_size": None if is_sig else 10.0,
                    "align": "left",
                    "confidence": 0.70,
                    "detection_source": "geometry",
                    "acroform_field_name": None,
                }
            )

    return mappings


def _deduplicate_field_keys_if_distinct_questions(mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    If two distinct questions accidentally slugify to the same field_key (e.g. two different
    'Date:' prompts in different sections like 'Start Date' vs 'End Date'), keep identical
    questions sharing one key (like repeated Full Name / Signature), while keeping
    checkbox options sharing their group key.
    """
    return mappings


# =============================================================================
# UNIFIED 4-STAGE ORCHESTRATOR
# =============================================================================
def analyze_pdf_document(pdf_path: str, use_vision: bool = True) -> Dict[str, Any]:
    """
    4-Stage Hybrid Universal PDF Analyzer:
      Stage 1: Full content + vector geometry + AcroForm scrape (PyMuPDF)
      Stage 2: Direct AcroForm extraction with nearest-label Q->A resolver
      Stage 3: Gemini Multimodal Vision + Geometry Snapping (when GEMINI_API_KEY is configured)
      Stage 4: Upgraded Offline Vector-Geometry Q->A Engine (fallback when offline)

    Returns a rich dict with:
      - mappings: List[Dict[str, Any]]
      - analysis_method: str
      - analysis_summary: Dict[str, Any]
      - scraped_storage: Dict[str, Any]
    """
    scrape = scrape_pdf_document(pdf_path)
    pages = scrape["pages"]
    scraped_storage = summarize_scraped_for_storage(scrape)

    all_mappings: List[Dict[str, Any]] = []
    vision_candidate_pages: List[Dict[str, Any]] = []
    acroform_pages_count = 0
    scanned_pages_count = 0
    methods_used: set[str] = set()
    warnings: List[str] = []

    for p in pages:
        pt = p["page_type"]
        if pt == "acroform":
            acro_fields = _extract_acroform_mappings(p)
            all_mappings.extend(acro_fields)
            acroform_pages_count += 1
            methods_used.add("acroform")
        else:
            if pt == "scanned_image":
                scanned_pages_count += 1
            # Queue digital_flat, scanned_image, and prose pages with signature cues for Vision
            has_sig_cue = bool(SIGNATURE_KEYWORDS.search(p.get("full_text", "")))
            if pt in ("digital_flat", "scanned_image") or has_sig_cue:
                vision_candidate_pages.append(p)

    has_vision_key = bool(use_vision and get_gemini_api_key())
    vision_model_used: Optional[str] = None
    vision_inspected_pages: set[int] = set()

    if vision_candidate_pages and has_vision_key:
        vision_res = analyze_pages_with_vision(pdf_path, vision_candidate_pages)
        vision_mappings = vision_res["mappings"]
        vision_inspected_pages = vision_res["inspected_pages"]
        vision_warn = vision_res["warning"]
        vision_model_used = vision_res["model_used"]

        page_summaries = vision_res["page_summaries"]
        page_key_values = vision_res["page_key_values"]
        page_ocr_text = vision_res["page_ocr_text"]

        # Enrich stored scraped data with Vision summaries, extracted key-values & OCR text
        for sp in scraped_storage.get("pages", []):
            pnum = sp["page_number"]
            if pnum in page_summaries:
                sp["page_summary"] = page_summaries[pnum]
            if pnum in page_ocr_text and len(sp.get("full_text", "").strip()) < 30:
                sp["full_text"] = page_ocr_text[pnum][:30000]
                sp["char_count"] = len(sp["full_text"])
                if not sp.get("structured_sections"):
                    sp["structured_sections"] = [
                        {
                            "title": "Scanned Page Text",
                            "lines": [line.strip() for line in sp["full_text"].splitlines() if line.strip()],
                        }
                    ]
            if pnum in page_key_values:
                existing_kvs = sp.setdefault("key_values", [])
                seen_kv = {(kv["key"].lower(), kv["value"].lower()) for kv in existing_kvs}
                for kv in page_key_values[pnum]:
                    sig = (kv["key"].lower(), kv["value"].lower())
                    if sig not in seen_kv:
                        seen_kv.add(sig)
                        existing_kvs.append(kv)

        if vision_warn:
            warnings.append(vision_warn)
        if vision_mappings:
            all_mappings.extend(vision_mappings)
            has_snapped = any(m["detection_source"] == "vision_snapped" for m in vision_mappings)
            methods_used.add("vision_hybrid" if has_snapped else "vision")
        elif vision_inspected_pages:
            methods_used.add("vision_readonly")

    # Stage 4: Run upgraded offline vector-geometry engine ONLY on pages not already inspected by Vision
    for p in vision_candidate_pages:
        if p["page_number"] in vision_inspected_pages:
            continue
        if p["page_type"] == "scanned_image":
            # Do NOT stamp fake dummy coordinates over scanned PDFs!
            continue
        geom_fields = _analyze_page_geometry_offline(p)
        if geom_fields:
            all_mappings.extend(geom_fields)
            methods_used.add("geometry")

    # Surface clear guidance when scanned pages exist without Vision API or local OCR
    unmapped_scanned = [
        p["page_number"]
        for p in pages
        if p["page_type"] == "scanned_image" and p["page_number"] not in vision_inspected_pages
    ]
    if unmapped_scanned and not has_vision_key:
        warnings.append(
            f"Page(s) {', '.join(map(str, unmapped_scanned))} appear to be scanned/image-only without selectable text. "
            f"Configure GEMINI_API_KEY for automatic Vision Q->A detection, or place fields manually in Adjust Boxes."
        )

    # Sort all mappings cleanly in reading order
    all_mappings.sort(
        key=lambda m: (
            int(m.get("page_number") or 1),
            round(float(m.get("y_pct") or 0.0), 2),
            round(float(m.get("x_pct") or 0.0), 2),
        )
    )
    all_mappings = _deduplicate_field_keys_if_distinct_questions(all_mappings)

    # Determine overall primary analysis_method label
    if not all_mappings and unmapped_scanned:
        analysis_method = "scanned_needs_vision"
    elif "vision_hybrid" in methods_used:
        analysis_method = "vision_hybrid"
    elif "vision" in methods_used:
        analysis_method = "vision"
    elif "vision_readonly" in methods_used and not all_mappings:
        analysis_method = "vision_readonly"
    elif "acroform" in methods_used and "geometry" in methods_used:
        analysis_method = "acroform_and_geometry"
    elif "acroform" in methods_used:
        analysis_method = "acroform"
    elif "geometry" in methods_used:
        analysis_method = "geometry"
    else:
        analysis_method = "manual"

    low_conf_count = sum(1 for m in all_mappings if (m.get("confidence") or 1.0) < 0.75)

    analysis_summary = {
        "analysis_method": analysis_method,
        "vision_model": vision_model_used if vision_inspected_pages else None,
        "page_count": scrape["page_count"],
        "page_type_counts": scrape["page_type_counts"],
        "ocr_available": scrape["ocr_available"],
        "total_mappings": len(all_mappings),
        "low_confidence_count": low_conf_count,
        "acroform_pages": acroform_pages_count,
        "scanned_pages": scanned_pages_count,
        "warnings": warnings,
    }

    return {
        "mappings": all_mappings,
        "analysis_method": analysis_method,
        "analysis_summary": analysis_summary,
        "scraped_storage": scraped_storage,
    }


def analyze_pdf_fields(pdf_path: str, use_vision: bool = True) -> List[Dict[str, Any]]:
    """Convenience wrapper returning just the list of detected field mappings."""
    return analyze_pdf_document(pdf_path, use_vision=use_vision)["mappings"]


def build_dictionary_format_from_mappings(
    template_id: int,
    document_name: str,
    page_count: int,
    mappings: List[Any],
    analysis_method: Optional[str] = None,
) -> DictionaryFormatResponse:
    """
    Single source of truth for generating the structured field specification and
    copyable `Key: Value` dictionary format from a document's field mappings.
    """
    field_map: Dict[str, DetectedFieldSummary] = {}
    field_order: List[str] = []

    split_key_redirect = {
        "dob_dd": ("date_of_birth", "Date of birth"),
        "dob_mm": ("date_of_birth", "Date of birth"),
        "dob_yyyy": ("date_of_birth", "Date of birth"),
        "date_dd": ("date_signed", "Date"),
        "date_mm": ("date_signed", "Date"),
        "date_yyyy": ("date_signed", "Date"),
    }

    sorted_mappings = sorted(
        mappings,
        key=lambda m: (
            getattr(m, "page_number", 1) or 1,
            round(float(getattr(m, "y_pct", 0.0) or 0.0), 2),
            round(float(getattr(m, "x_pct", 0.0) or 0.0), 2),
        ),
    )

    for m in sorted_mappings:
        m_type = getattr(m, "type", "text") or "text"
        raw_key = getattr(m, "field_key", "field")
        raw_label = getattr(m, "label", None)
        q_text = getattr(m, "question_text", None)
        section = getattr(m, "section", None)
        match_val = getattr(m, "match_value", None)
        p_num = getattr(m, "page_number", 1) or 1
        conf = getattr(m, "confidence", None)
        source = getattr(m, "detection_source", None)

        if raw_key in split_key_redirect:
            f_key, f_label = split_key_redirect[raw_key]
            m_type = "text"
        else:
            f_key = raw_key
            f_label = humanize_key(f_key, raw_label)

        if f_key not in field_map:
            field_map[f_key] = DetectedFieldSummary(
                field_key=f_key,
                label=f_label,
                question_text=q_text,
                section=section,
                type=m_type,
                options=[],
                page_numbers=[p_num],
                confidence=conf,
                detection_source=source,
            )
            field_order.append(f_key)
        else:
            summary = field_map[f_key]
            if p_num not in summary.page_numbers:
                summary.page_numbers.append(p_num)
            if m_type == "checkbox":
                summary.type = "checkbox"
            elif m_type == "multiline" and summary.type == "text":
                summary.type = "multiline"
            if conf is not None and (summary.confidence is None or conf < summary.confidence):
                summary.confidence = conf
            if not summary.question_text and q_text:
                summary.question_text = q_text
            if not summary.section and section:
                summary.section = section

        if m_type == "checkbox" and match_val:
            if match_val not in field_map[f_key].options:
                field_map[f_key].options.append(match_val)

    text_and_cb = [field_map[k] for k in field_order if field_map[k].type != "image"]
    image_fields = [field_map[k] for k in field_order if field_map[k].type == "image"]
    ordered_summaries = text_and_cb + image_fields

    blank_lines: List[str] = []
    guided_lines: List[str] = []

    for f in text_and_cb:
        blank_lines.append(f"{f.label}: ")
        if f.type == "checkbox" and f.options:
            opts_str = " / ".join(f.options)
            guided_lines.append(f"{f.label} ({opts_str}): ")
        else:
            guided_lines.append(f"{f.label}: ")

    return DictionaryFormatResponse(
        template_id=template_id,
        document_name=document_name,
        page_count=page_count,
        analysis_method=analysis_method,
        total_mappings=len(mappings),
        fields=ordered_summaries,
        blank_dictionary_text="\n".join(blank_lines),
        guided_dictionary_text="\n".join(guided_lines),
    )

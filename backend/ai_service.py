import json
import os
import re
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from models import ParseTextResponse
from pdf_analyzer import normalize_label_to_key_and_label

load_dotenv()


def get_text_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"


MODEL_NAME = get_text_model_name()

SYSTEM_PROMPT = """You are a universal PDF form data extraction assistant.
Extract and normalize form field values from the user's pasted Key: Value dictionary text or unstructured message.
Rules:
1. Map values ONLY to the target document fields provided in the schema.
2. For checkbox / choice fields with allowed options, return ONLY one of the exact allowed option strings (or null if not mentioned).
3. If full_name is provided and the target fields ask for first_name / last_name / surname, split them cleanly (and vice versa if first_name + last_name are given and full_name is requested).
4. Leave any field that is not stated in the input strictly as null — NEVER guess or invent values.
5. Ignore unedited placeholder hints like "(Option A / Option B)" or "[YYYY-MM-DD]"."""


def _compact_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _normalize_checkbox_option(raw_val: str, options: List[str]) -> str:
    """Matches a user-typed checkbox value against the exact allowed option labels."""
    val_clean = (raw_val or "").strip()
    if not val_clean or not options:
        return val_clean
    val_low = val_clean.lower()
    val_comp = _compact_token(val_clean)

    for opt in options:
        if opt.lower() == val_low or _compact_token(opt) == val_comp:
            return opt

    # Common boolean shorthand normalization (y/n/true/false)
    if val_low in ("y", "yes", "true", "checked", "1"):
        for opt in options:
            if opt.lower() in ("yes", "true", "agree"):
                return opt
    if val_low in ("n", "no", "false", "unchecked", "0"):
        for opt in options:
            if opt.lower() in ("no", "false"):
                return opt

    # Single-letter abbreviation for Gender (m/f) when options include Male/Female
    if val_low == "m":
        for opt in options:
            if opt.lower() == "male":
                return opt
    if val_low == "f":
        for opt in options:
            if opt.lower() == "female":
                return opt

    return val_clean


def _sync_name_fields(
    data: Dict[str, Any],
    allowed_keys: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """
    Synchronizes first_name / last_name / surname / other_names / full_name cleanly.
    When allowed_keys is supplied, only populates name aliases that the active PDF actually uses.
    """

    def should_set(k: str) -> bool:
        return allowed_keys is None or k in allowed_keys

    # Sync last_name <-> surname
    if data.get("last_name") and not data.get("surname") and should_set("surname"):
        data["surname"] = data["last_name"]
    elif data.get("surname") and not data.get("last_name") and should_set("last_name"):
        data["last_name"] = data["surname"]

    # Sync first_name <-> other_names
    if data.get("first_name") and not data.get("other_names") and should_set("other_names"):
        if data.get("middle_name"):
            data["other_names"] = f"{data['first_name']} {data['middle_name']}".strip()
        else:
            data["other_names"] = data["first_name"]
    elif data.get("other_names") and not data.get("first_name") and should_set("first_name"):
        parts = str(data["other_names"]).strip().split()
        if parts:
            data["first_name"] = parts[0]

    # Split full_name -> first_name / last_name / surname / other_names
    if data.get("full_name"):
        words = str(data["full_name"]).strip().split()
        title_words = {"mr", "mrs", "miss", "ms", "dr", "prof", "chief", "engr", "rev"}
        if words and words[0].lower().rstrip(".") in title_words:
            words = words[1:]
        if len(words) >= 2:
            if not data.get("last_name") and should_set("last_name"):
                data["last_name"] = words[-1]
            if not data.get("surname") and should_set("surname"):
                data["surname"] = words[-1]
            if not data.get("first_name") and should_set("first_name"):
                data["first_name"] = words[0]
            if not data.get("other_names") and should_set("other_names"):
                data["other_names"] = " ".join(words[:-1])
        elif len(words) == 1:
            if not data.get("last_name") and should_set("last_name"):
                data["last_name"] = words[0]
            if not data.get("surname") and should_set("surname"):
                data["surname"] = words[0]

    # Combine given + family -> full_name
    given = data.get("other_names") or data.get("first_name")
    fam = data.get("last_name") or data.get("surname")
    if given and fam and not data.get("full_name") and should_set("full_name"):
        data["full_name"] = f"{given} {fam}".strip()

    return data


def _parse_dictionary_and_labels(
    raw_text: str,
    expected_fields: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Clean, deterministic, domain-agnostic Key: Value parser.
    Supports:
      - Exact `Label: Value` and `Label (Opt1 / Opt2): Value` dictionary lines
      - Multi-line continuation values (for paragraphs/addresses)
      - Matching against `field_key`, `label`, `question_text`, and universal synonyms
      - Exact checkbox option normalization without false-positive whole-text guessing
    """
    extracted: Dict[str, Any] = {}

    expected_lookup: Dict[str, str] = {}
    options_by_key: Dict[str, List[str]] = {}
    allowed_keys: Optional[set[str]] = None

    if expected_fields:
        allowed_keys = set()
        for ef in expected_fields:
            fk = ef.get("field_key")
            if not fk or ef.get("type") == "image":
                continue
            allowed_keys.add(fk)
            if ef.get("options"):
                options_by_key[fk] = [str(o) for o in ef["options"] if o]

            for candidate in (fk, ef.get("label"), ef.get("question_text")):
                if not candidate:
                    continue
                c_low = str(candidate).strip().lower().rstrip(":?")
                expected_lookup[c_low] = fk
                comp = _compact_token(c_low)
                if comp:
                    expected_lookup[comp] = fk

    last_matched_key: Optional[str] = None

    for raw_line in raw_text.splitlines():
        stripped = raw_line.replace("*", "").replace("`", "").strip()
        if not stripped:
            last_matched_key = None
            continue

        # Strip leading list markers like "1. ", "- ", "• "
        clean_line = re.sub(r"^[\s\-\•\*\u2022\u25aa\u25cf]+|\d+[\.\)]\s*", "", stripped).strip()
        if not clean_line:
            continue

        if ":" in clean_line:
            key_part, val_part = clean_line.split(":", 1)
            key_part = key_part.strip()
            val_part = val_part.strip()

            # Heuristic guard: avoid treating URLs ("https://...") or timestamps as keys
            if key_part.lower() in ("http", "https", "mailto") or len(key_part) > 100:
                if last_matched_key:
                    extracted[last_matched_key] = f"{extracted[last_matched_key]}\n{clean_line}".strip()
                continue

            # Strip trailing parenthetical hints like "Gender (Male / Female)"
            key_no_parens = re.sub(r"\s*\([^\)]*\)\s*$", "", key_part).strip().rstrip("?")
            key_comp = _compact_token(key_no_parens)

            matched_key = (
                expected_lookup.get(key_part.lower())
                or expected_lookup.get(key_no_parens.lower())
                or expected_lookup.get(key_comp)
            )

            # Fallback to canonical universal synonym normalization
            norm_key, _ = normalize_label_to_key_and_label(key_no_parens)
            if not matched_key:
                if allowed_keys is None:
                    matched_key = norm_key if norm_key != "custom_field" else None
                elif norm_key in allowed_keys:
                    matched_key = norm_key
                else:
                    # Try matching normalized synonym label against expected_lookup
                    matched_key = expected_lookup.get(norm_key) or expected_lookup.get(_compact_token(norm_key))

            # Skip blank values or unedited placeholder hints like "(Yes / No)" or "[DD/MM/YYYY]"
            is_placeholder = (
                not val_part
                or (val_part.startswith("(") and val_part.endswith(")"))
                or (val_part.startswith("[") and val_part.endswith("]"))
            )
            if is_placeholder:
                last_matched_key = matched_key
                continue

            target_keys = []
            if matched_key:
                target_keys.append(matched_key)
            if (
                allowed_keys is None
                and norm_key
                and norm_key != "custom_field"
                and norm_key not in target_keys
            ):
                target_keys.append(norm_key)

            for tk in target_keys:
                final_val = val_part
                if tk in options_by_key:
                    final_val = _normalize_checkbox_option(val_part, options_by_key[tk])
                extracted[tk] = final_val

            last_matched_key = matched_key
        elif last_matched_key and last_matched_key in extracted:
            # Continuation line for multi-line answers (e.g. long addresses or explanations)
            extracted[last_matched_key] = f"{extracted[last_matched_key]}\n{clean_line}".strip()

    _sync_name_fields(extracted, allowed_keys=allowed_keys)
    return {k: v for k, v in extracted.items() if v is not None and str(v).strip() != ""}


def _build_dynamic_extraction_schema(
    expected_fields: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Builds a strict JSON Schema matching the active PDF's detected fields and checkbox enums."""
    if not expected_fields:
        return None

    properties: Dict[str, Any] = {}
    for ef in expected_fields:
        fk = ef.get("field_key")
        if not fk or ef.get("type") == "image":
            continue
        desc = ef.get("question_text") or ef.get("label") or fk
        opts = [str(o) for o in (ef.get("options") or []) if o]
        if ef.get("type") == "checkbox" and opts:
            properties[fk] = {
                "anyOf": [
                    {"type": "string", "enum": opts},
                    {"type": "null"},
                ],
                "description": f"{desc}. Must be one of {opts} or null.",
            }
        else:
            properties[fk] = {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "description": str(desc),
            }

    if not properties:
        return None

    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def parse_input_text(
    raw_text: str,
    expected_fields: Optional[List[Dict[str, Any]]] = None,
) -> ParseTextResponse:
    """
    Universal parser for filled `Key: Value` dictionaries and unstructured text/messages.
    Uses deterministic dictionary parsing first, then enhances with Gemini 4 (`gemini-4-hydrogen`)
    via the Interactions API with strict dynamic JSON Schema when GEMINI_API_KEY is configured.
    """
    heuristic_data = _parse_dictionary_and_labels(raw_text, expected_fields)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return ParseTextResponse(
            fields=heuristic_data,
            parser_used="dictionary-heuristic",
            warning=None,
        )

    model_name = get_text_model_name()
    schema = _build_dynamic_extraction_schema(expected_fields)
    options_by_key = {
        ef["field_key"]: [str(o) for o in ef.get("options", []) if o]
        for ef in (expected_fields or [])
        if ef.get("field_key") and ef.get("options")
    }
    allowed_keys = (
        {ef["field_key"] for ef in expected_fields if ef.get("field_key") and ef.get("type") != "image"}
        if expected_fields
        else None
    )

    try:
        client = genai.Client(api_key=api_key, http_options={"timeout": 30000})

        field_guide_lines = []
        for ef in (expected_fields or []):
            if ef.get("type") == "image" or not ef.get("field_key"):
                continue
            opts_hint = f" | options: {ef['options']}" if ef.get("options") else ""
            q_hint = f" | question: {ef['question_text']}" if ef.get("question_text") else ""
            field_guide_lines.append(f"- {ef['field_key']} ({ef.get('label', ef['field_key'])}{opts_hint}{q_hint})")

        field_guide = (
            "Target Document Fields:\n" + "\n".join(field_guide_lines) + "\n\n"
            if field_guide_lines
            else "Return a flat JSON object mapping clean snake_case field keys to extracted string values.\n\n"
        )
        user_input = f"{field_guide}User Input Text:\n{raw_text}"

        response_format: Dict[str, Any] = {
            "type": "text",
            "mime_type": "application/json",
        }
        if schema:
            response_format["schema"] = schema

        interaction = client.interactions.create(
            model=model_name,
            system_instruction=SYSTEM_PROMPT,
            input=user_input,
            generation_config={"thinking_level": "minimal"},
            response_format=response_format,
            store=False,
        )

        raw_out = getattr(interaction, "output_text", None) or ""
        ai_dict = json.loads(raw_out) if raw_out.strip() else {}

        merged = dict(heuristic_data)
        if isinstance(ai_dict, dict):
            for k, v in ai_dict.items():
                if v is None:
                    continue
                v_str = str(v).strip()
                if not v_str:
                    continue
                if k in options_by_key:
                    v_str = _normalize_checkbox_option(v_str, options_by_key[k])
                merged[k] = v_str

        _sync_name_fields(merged, allowed_keys=allowed_keys)
        return ParseTextResponse(
            fields=merged,
            parser_used=model_name,
            warning=None,
        )
    except Exception as exc:
        return ParseTextResponse(
            fields=heuristic_data,
            parser_used="dictionary-heuristic",
            warning=f"Gemini API call failed ({exc}); fell back to deterministic dictionary parser.",
        )

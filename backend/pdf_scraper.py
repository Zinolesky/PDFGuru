import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
import pymupdf


def is_local_ocr_available() -> bool:
    """Checks whether Tesseract OCR is available on PATH for optional offline scanned-PDF OCR."""
    return bool(shutil.which("tesseract") or os.getenv("TESSDATA_PREFIX"))


def _norm(val: float, denom: float) -> float:
    return round(max(0.0, min(1.0, val / max(1.0, denom))), 4)


def _extract_lines_from_text_dict(
    text_dict: Dict[str, Any], pw: float, ph: float
) -> Tuple[List[Dict[str, Any]], int]:
    """Extracts reading-order text lines with font size, bold flag, and normalized rects."""
    lines: List[Dict[str, Any]] = []
    total_chars = 0

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            total_chars += len(text)
            bbox = line.get("bbox", [0, 0, 0, 0])
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])

            sizes = [float(s.get("size", 10.0)) for s in spans if s.get("text", "").strip()]
            avg_size = round(sum(sizes) / max(1, len(sizes)), 2) if sizes else 10.0
            is_bold = any(
                bool(int(s.get("flags", 0)) & 16) or "bold" in str(s.get("font", "")).lower()
                for s in spans
                if s.get("text", "").strip()
            )
            lines.append(
                {
                    "text": text,
                    "x0": round(x0, 2),
                    "y0": round(y0, 2),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x_pct": _norm(x0, pw),
                    "y_pct": _norm(y0, ph),
                    "w_pct": _norm(max(0.0, x1 - x0), pw),
                    "h_pct": _norm(max(0.0, y1 - y0), ph),
                    "font_size": avg_size,
                    "is_bold": is_bold,
                }
            )

    lines.sort(key=lambda item: (round(item["y0"] / max(4.0, ph * 0.008)), item["x0"]))
    return lines, total_chars


def _extract_image_coverage(page: pymupdf.Page, pw: float, ph: float) -> float:
    """Computes approximate fraction of the page covered by embedded raster images."""
    page_area = max(1.0, pw * ph)
    covered = 0.0
    try:
        for img_info in page.get_image_info(xrefs=False):
            bbox = img_info.get("bbox")
            if not bbox:
                continue
            ix0 = max(0.0, min(pw, float(bbox[0])))
            iy0 = max(0.0, min(ph, float(bbox[1])))
            ix1 = max(0.0, min(pw, float(bbox[2])))
            iy1 = max(0.0, min(ph, float(bbox[3])))
            covered += max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    except Exception:
        pass
    return round(min(1.0, covered / page_area), 3)


def _extract_widgets(page: pymupdf.Page, pw: float, ph: float) -> List[Dict[str, Any]]:
    """Extracts all interactive AcroForm widgets on a page."""
    widgets_out: List[Dict[str, Any]] = []
    for w in list(page.widgets() or []):
        r = w.rect
        w_type = w.field_type
        if w_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
            kind = "checkbox"
        elif w_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
            kind = "radio"
        elif w_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            kind = "signature"
        elif w_type in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
            kind = "choice"
        else:
            is_multiline = bool(getattr(w, "field_flags", 0) & getattr(pymupdf, "PDF_TX_FIELD_IS_MULTILINE", 4096))
            kind = "multiline" if (is_multiline or r.height >= max(34.0, ph * 0.045)) else "text"

        on_state = None
        try:
            if hasattr(w, "on_state") and callable(w.on_state):
                st = w.on_state()
                if st and str(st).lower() != "off":
                    on_state = str(st).lstrip("/")
        except Exception:
            pass

        if not on_state:
            try:
                if hasattr(w, "button_states") and callable(w.button_states):
                    states = w.button_states() or {}
                    normal = states.get("normal") or []
                    for s in normal:
                        s_clean = str(s).lstrip("/")
                        if s_clean.lower() != "off":
                            on_state = s_clean
                            break
            except Exception:
                pass

        choice_vals: List[str] = []
        try:
            if getattr(w, "choice_values", None):
                for cv in w.choice_values:
                    if isinstance(cv, (list, tuple)) and cv:
                        choice_vals.append(str(cv[-1]))
                    elif cv:
                        choice_vals.append(str(cv))
        except Exception:
            pass

        widgets_out.append(
            {
                "field_name": (w.field_name or "").strip(),
                "field_label": (w.field_label or "").strip(),
                "kind": kind,
                "on_state": on_state,
                "choice_values": choice_vals,
                "x0": round(float(r.x0), 2),
                "y0": round(float(r.y0), 2),
                "x1": round(float(r.x1), 2),
                "y1": round(float(r.y1), 2),
                "x_pct": _norm(r.x0, pw),
                "y_pct": _norm(r.y0, ph),
                "w_pct": _norm(r.width, pw),
                "h_pct": _norm(r.height, ph),
                "cx_pct": _norm(r.x0 + r.width * 0.5, pw),
                "cy_pct": _norm(r.y0 + r.height * 0.5, ph),
            }
        )
    return widgets_out


def _dedupe_rects(rects: List[Dict[str, Any]], tol: float = 0.008) -> List[Dict[str, Any]]:
    """Removes near-duplicate vector rectangles/lines."""
    out: List[Dict[str, Any]] = []
    for item in rects:
        dup = False
        for prev in out:
            if (
                abs(item["x_pct"] - prev["x_pct"]) <= tol
                and abs(item["y_pct"] - prev["y_pct"]) <= tol
                and abs(item["w_pct"] - prev["w_pct"]) <= tol
                and abs(item["h_pct"] - prev["h_pct"]) <= tol
            ):
                dup = True
                break
        if not dup:
            out.append(item)
    return out


def _extract_table_cells_from_segments(
    h_segments: List[Tuple[float, float, float]],
    v_segments: List[Tuple[float, float, float]],
    pw: float,
    ph: float,
    scale: float,
) -> List[Dict[str, Any]]:
    """Detects rectangular grid/table cells formed by intersecting horizontal and vertical rules."""
    if len(h_segments) < 2 or len(v_segments) < 2:
        return []

    tol = 4.0 * scale

    # Cluster y-coordinates of horizontal lines and x-coordinates of vertical lines
    def cluster_vals(vals: List[float]) -> List[float]:
        if not vals:
            return []
        vals_sorted = sorted(vals)
        groups: List[List[float]] = [[vals_sorted[0]]]
        for v in vals_sorted[1:]:
            if abs(v - groups[-1][-1]) <= tol:
                groups[-1].append(v)
            else:
                groups.append([v])
        return [sum(g) / len(g) for g in groups]

    # Only consider segments long enough to be part of a grid
    long_h = [seg for seg in h_segments if (seg[1] - seg[0]) >= 60.0 * scale]
    long_v = [seg for seg in v_segments if (seg[1] - seg[0]) >= 14.0 * scale]
    if len(long_h) < 2 or len(long_v) < 2:
        return []

    ys = cluster_vals([s[2] for s in long_h])
    xs = cluster_vals([s[2] for s in long_v])

    if len(ys) < 2 or len(xs) < 2 or len(ys) > 80 or len(xs) > 25:
        return []

    def has_h_edge(x_a: float, x_b: float, y_val: float) -> bool:
        for sx0, sx1, sy in long_h:
            if abs(sy - y_val) <= tol and sx0 <= x_a + tol and sx1 >= x_b - tol:
                return True
        return False

    def has_v_edge(y_a: float, y_b: float, x_val: float) -> bool:
        for sy0, sy1, sx in long_v:
            if abs(sx - x_val) <= tol and sy0 <= y_a + tol and sy1 >= y_b - tol:
                return True
        return False

    cells: List[Dict[str, Any]] = []
    for ri in range(len(ys) - 1):
        y0, y1 = ys[ri], ys[ri + 1]
        ch = y1 - y0
        if ch < 11.0 * scale or ch > ph * 0.45:
            continue
        row_xs = [(xi, xv) for xi, xv in enumerate(xs) if has_v_edge(y0, y1, xv)]
        if len(row_xs) < 3:
            continue
        for k in range(len(row_xs) - 1):
            xi, x0 = row_xs[k]
            _, x1 = row_xs[k + 1]
            cw = x1 - x0
            if cw < 24.0 * scale or cw > pw * 0.96:
                continue
            if has_h_edge(x0, x1, y0) and has_h_edge(x0, x1, y1):
                cells.append(
                    {
                        "x0": round(x0, 2),
                        "y0": round(y0, 2),
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x_pct": _norm(x0, pw),
                        "y_pct": _norm(y0, ph),
                        "w_pct": _norm(cw, pw),
                        "h_pct": _norm(ch, ph),
                        "row_idx": ri,
                        "col_idx": xi,
                    }
                )
    return _dedupe_rects(cells)


def _extract_vector_geometry(page: pymupdf.Page, pw: float, ph: float) -> Dict[str, List[Dict[str, Any]]]:
    """
    Inspects PDF vector paths (`page.get_drawings()`) to identify:
      - underlines: horizontal rules for write-in text/signatures
      - checkbox_candidates: small empty squares or circles
      - text_boxes: rectangular input fields
      - large_boxes: big bordered boxes (photo, stamp, or multiline blocks)
      - table_cells: cells formed by intersecting horizontal/vertical grid lines
    """
    scale = max(0.5, pw / 595.0)
    underlines: List[Dict[str, Any]] = []
    checkbox_candidates: List[Dict[str, Any]] = []
    text_boxes: List[Dict[str, Any]] = []
    large_boxes: List[Dict[str, Any]] = []

    h_segments: List[Tuple[float, float, float]] = []
    v_segments: List[Tuple[float, float, float]] = []

    try:
        drawings = page.get_drawings() or []
    except Exception:
        drawings = []

    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
        w = max(0.0, x1 - x0)
        h = max(0.0, y1 - y0)
        if w <= 0.1 and h <= 0.1:
            continue

        # Skip full-page decorative borders / background fills
        if w > pw * 0.94 and h > ph * 0.85:
            continue

        fill = d.get("fill")
        stroke = d.get("color")
        items = d.get("items") or []

        # Collect individual line segments for table grid reconstruction
        for item in items:
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                dx = abs(p2.x - p1.x)
                dy = abs(p2.y - p1.y)
                if dx >= 25.0 * scale and dy <= 2.5 * scale:
                    h_segments.append((min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) * 0.5))
                elif dy >= 10.0 * scale and dx <= 2.5 * scale:
                    v_segments.append((min(p1.y, p2.y), max(p1.y, p2.y), (p1.x + p2.x) * 0.5))
            elif op == "re":
                r = item[1]
                if r.width >= 20.0 * scale and r.height >= 10.0 * scale:
                    h_segments.append((r.x0, r.x1, r.y0))
                    h_segments.append((r.x0, r.x1, r.y1))
                    v_segments.append((r.y0, r.y1, r.x0))
                    v_segments.append((r.y0, r.y1, r.x1))

        # Ignore dark solid banner fills (not blank input boxes)
        is_dark_fill = False
        if fill is not None and isinstance(fill, (tuple, list)) and len(fill) >= 3:
            lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
            if lum < 0.72 and h > 6.0 * scale:
                is_dark_fill = True
        if is_dark_fill:
            continue

        # 1. Horizontal underline / rule
        if w >= 28.0 * scale and h <= 3.5 * scale:
            # Skip full-width decorative header/footer divider rules near extreme top/bottom
            if not (w > pw * 0.90 and (y0 < ph * 0.05 or y0 > ph * 0.96)):
                underlines.append(
                    {
                        "x0": round(x0, 2),
                        "y0": round(y0, 2),
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x_pct": _norm(x0, pw),
                        "y_pct": _norm(y0, ph),
                        "w_pct": _norm(w, pw),
                        "h_pct": _norm(max(1.0, h), ph),
                    }
                )
            continue

        # Must have a visible stroke or light input background fill to be a box/checkbox
        if stroke is None and fill is None:
            continue

        # 2. Small square or circle -> checkbox / radio candidate
        min_cb = 5.5 * scale
        max_cb = 22.0 * scale
        if min_cb <= w <= max_cb and min_cb <= h <= max_cb:
            aspect = w / max(0.1, h)
            if 0.65 <= aspect <= 1.55:
                checkbox_candidates.append(
                    {
                        "x0": round(x0, 2),
                        "y0": round(y0, 2),
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x_pct": _norm(x0, pw),
                        "y_pct": _norm(y0, ph),
                        "w_pct": _norm(w, pw),
                        "h_pct": _norm(h, ph),
                        "cx_pct": _norm(x0 + w * 0.5, pw),
                        "cy_pct": _norm(y0 + h * 0.5, ph),
                    }
                )
            continue

        # 3. Rectangular input box or large frame (photo/multiline/signature)
        if w >= 32.0 * scale and h >= 11.0 * scale:
            box_entry = {
                "x0": round(x0, 2),
                "y0": round(y0, 2),
                "x1": round(x1, 2),
                "y1": round(y1, 2),
                "x_pct": _norm(x0, pw),
                "y_pct": _norm(y0, ph),
                "w_pct": _norm(w, pw),
                "h_pct": _norm(h, ph),
            }
            if h >= 62.0 * scale and w <= pw * 0.42:
                large_boxes.append(box_entry)
            elif h <= ph * 0.35 and w <= pw * 0.94:
                text_boxes.append(box_entry)

    table_cells = _extract_table_cells_from_segments(h_segments, v_segments, pw, ph, scale)

    return {
        "underlines": _dedupe_rects(underlines),
        "checkbox_candidates": _dedupe_rects(checkbox_candidates, tol=0.005),
        "text_boxes": _dedupe_rects(text_boxes),
        "large_boxes": _dedupe_rects(large_boxes),
        "table_cells": table_cells,
    }


def _detect_sections(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identifies likely section headings (bold / larger font / ALL CAPS short headers)."""
    if not lines:
        return []
    sizes = sorted(ln["font_size"] for ln in lines)
    median_size = sizes[len(sizes) // 2] if sizes else 10.0

    sections: List[Dict[str, Any]] = []
    for ln in lines:
        txt = ln["text"].strip()
        if len(txt) < 3 or len(txt) > 90:
            continue
        if txt.endswith(":") or "____" in txt or "...." in txt:
            continue
        is_heading_pattern = bool(
            re.match(r"^(?:section|part|step)\s+[a-z0-9]+", txt, re.IGNORECASE)
            or (ln["is_bold"] and ln["font_size"] >= median_size + 0.5)
            or (txt.isupper() and len(txt.split()) <= 8 and ln["font_size"] >= median_size)
        )
        if is_heading_pattern:
            sections.append(
                {
                    "title": txt,
                    "y_pct": ln["y_pct"],
                    "x_pct": ln["x_pct"],
                }
            )
    return sections


def _extract_key_values_from_lines(lines: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Extracts already-populated `Key: Value` informational pairs from a page's lines."""
    kvs: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for ln in lines:
        txt = ln["text"].strip()
        if ":" not in txt or len(txt) > 220:
            continue
        k, v = txt.split(":", 1)
        k = k.strip()
        v = v.strip()
        if len(k) < 2 or len(k) > 60 or not re.search(r"[a-zA-Z]", k):
            continue
        if k.lower() in ("http", "https", "mailto", "tel"):
            continue
        if not v or v.startswith("//"):
            continue
        # Skip blank placeholders like ____, ...., (  ), [  ]
        if re.fullmatch(r"[\s_\.\-\(\)\[\]☐□/]+", v):
            continue
        if re.match(r"^[_]{3,}$|^[\.]{4,}$", v):
            continue
        sig = (k.lower(), v)
        if sig not in seen:
            seen.add(sig)
            kvs.append({"key": k, "value": v})
    return kvs


def _extract_tables_from_cells(
    table_cells: List[Dict[str, Any]],
    lines: List[Dict[str, Any]],
) -> List[List[List[str]]]:
    """Reconstructs 2D text tables from detected table cell bounding boxes."""
    if not table_cells:
        return []

    by_row: Dict[int, Dict[int, Dict[str, Any]]] = {}
    all_cols: set[int] = set()
    for cell in table_cells:
        ri = int(cell["row_idx"])
        ci = int(cell["col_idx"])
        by_row.setdefault(ri, {})[ci] = cell
        all_cols.add(ci)

    sorted_cols = sorted(all_cols)
    sorted_rows = sorted(by_row.keys())
    if not sorted_rows or not sorted_cols:
        return []

    def cell_text(c: Dict[str, Any]) -> str:
        bx0, by0 = c["x_pct"] - 0.004, c["y_pct"] - 0.004
        bx1, by1 = c["x_pct"] + c["w_pct"] + 0.004, c["y_pct"] + c["h_pct"] + 0.004
        hits = []
        for ln in lines:
            lcx = ln["x_pct"] + ln["w_pct"] * 0.5
            lcy = ln["y_pct"] + ln["h_pct"] * 0.5
            if bx0 <= lcx <= bx1 and by0 <= lcy <= by1:
                hits.append(ln["text"].strip())
        return " ".join(hits).strip()

    tables: List[List[List[str]]] = []
    current_table: List[List[str]] = []
    prev_r: Optional[int] = None

    for ri in sorted_rows:
        if prev_r is not None and ri > prev_r + 1 and current_table:
            tables.append(current_table)
            current_table = []
        row_map = by_row[ri]
        row_vals = [cell_text(row_map[ci]) if ci in row_map else "" for ci in sorted_cols]
        if any(v for v in row_vals):
            current_table.append(row_vals)
        prev_r = ri

    if current_table:
        tables.append(current_table)

    return tables


def _group_lines_by_sections(
    lines: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Groups reading-order lines under their preceding section heading."""
    if not lines:
        return []
    if not sections:
        return [{"title": "Document Content", "lines": [ln["text"] for ln in lines]}]

    grouped: List[Dict[str, Any]] = []
    sec_lookup: List[Tuple[float, str]] = [(s["y_pct"], s["title"]) for s in sections]
    used_sec: set[int] = set()

    current_title = "Document Content"
    current_lines: List[str] = []

    for ln in lines:
        txt = ln["text"].strip()
        if not txt:
            continue
        matched_sec_idx = None
        for idx, (sy, stitle) in enumerate(sec_lookup):
            if idx not in used_sec and txt == stitle and abs(ln["y_pct"] - sy) <= 0.003:
                matched_sec_idx = idx
                break
        if matched_sec_idx is not None:
            used_sec.add(matched_sec_idx)
            if current_lines:
                grouped.append({"title": current_title, "lines": current_lines})
            current_title = sec_lookup[matched_sec_idx][1]
            current_lines = []
        else:
            current_lines.append(txt)

    if current_lines or current_title != "Document Content":
        grouped.append({"title": current_title, "lines": current_lines})

    return grouped


def scrape_pdf_document(pdf_path: str) -> Dict[str, Any]:
    """
    Stage 1 Universal PDF Scraper.
    Extracts every page's full text, lines, font hierarchy, section headings,
    native AcroForm widgets, and vector form geometry (underlines, boxes, tables, checkboxes).
    Also classifies each page: 'acroform', 'digital_flat', 'scanned_image', or 'prose'.
    """
    doc = pymupdf.open(pdf_path)
    pages_data: List[Dict[str, Any]] = []
    ocr_available = is_local_ocr_available()

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pw = max(1.0, float(page.rect.width))
        ph = max(1.0, float(page.rect.height))
        page_num = page_idx + 1

        widgets = _extract_widgets(page, pw, ph)
        text_dict = page.get_text("dict")
        lines, total_chars = _extract_lines_from_text_dict(text_dict, pw, ph)
        image_coverage = _extract_image_coverage(page, pw, ph)
        geometry = _extract_vector_geometry(page, pw, ph)

        ocr_used = False
        # Optional local OCR hook when page appears scanned and Tesseract is installed
        if total_chars < 25 and image_coverage >= 0.40 and not widgets and ocr_available:
            try:
                tp = page.get_textpage_ocr(flags=pymupdf.TEXTFLAGS_TEXT, dpi=200, full=True)
                ocr_dict = page.get_text("dict", textpage=tp)
                ocr_lines, ocr_chars = _extract_lines_from_text_dict(ocr_dict, pw, ph)
                if ocr_chars > total_chars:
                    lines = ocr_lines
                    total_chars = ocr_chars
                    ocr_used = True
            except Exception:
                pass

        sections = _detect_sections(lines)
        full_text = "\n".join(ln["text"] for ln in lines)
        key_values = _extract_key_values_from_lines(lines)
        tables = _extract_tables_from_cells(geometry.get("table_cells", []), lines)
        structured_sections = _group_lines_by_sections(lines, sections)

        # Form signal heuristic for page classification
        has_text_form_cues = bool(
            re.search(
                r"(?:[:\?]\s*$|[\._]{4,}|[☐□■]|\[[\s_]{1,3}\]|\(\s{1,5}\)|\bsignature\b|\bdate\b)",
                full_text,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        geometry_count = (
            len(geometry["underlines"])
            + len(geometry["checkbox_candidates"])
            + len(geometry["text_boxes"])
            + len(geometry["table_cells"])
            + len(geometry["large_boxes"])
        )

        if len(widgets) >= 1:
            page_type = "acroform"
        elif total_chars < 30 and image_coverage >= 0.35 and not ocr_used:
            page_type = "scanned_image"
        elif geometry_count >= 1 or has_text_form_cues:
            page_type = "digital_flat"
        else:
            page_type = "prose"

        pages_data.append(
            {
                "page_number": page_num,
                "width": round(pw, 2),
                "height": round(ph, 2),
                "page_type": page_type,
                "ocr_used": ocr_used,
                "char_count": total_chars,
                "image_coverage": image_coverage,
                "full_text": full_text,
                "sections": sections,
                "structured_sections": structured_sections,
                "key_values": key_values,
                "tables": tables,
                "lines": lines,
                "widgets": widgets,
                "geometry": geometry,
            }
        )

    doc.close()

    type_counts: Dict[str, int] = {}
    for p in pages_data:
        pt = p["page_type"]
        type_counts[pt] = type_counts.get(pt, 0) + 1

    return {
        "page_count": len(pages_data),
        "ocr_available": ocr_available,
        "page_type_counts": type_counts,
        "pages": pages_data,
    }


def summarize_scraped_for_storage(scrape_result: Dict[str, Any]) -> Dict[str, Any]:
    """Creates a clean, lightweight JSON-serializable summary of scraped content for the UI."""
    pages_summary: List[Dict[str, Any]] = []
    for p in scrape_result.get("pages", []):
        geom = p.get("geometry", {})
        pages_summary.append(
            {
                "page_number": p["page_number"],
                "page_type": p["page_type"],
                "width": p["width"],
                "height": p["height"],
                "char_count": p["char_count"],
                "image_coverage": p["image_coverage"],
                "ocr_used": p.get("ocr_used", False),
                "page_summary": None,
                "sections": [s["title"] for s in p.get("sections", [])],
                "structured_sections": p.get("structured_sections", []),
                "key_values": p.get("key_values", []),
                "tables": p.get("tables", []),
                "widget_count": len(p.get("widgets", [])),
                "underline_count": len(geom.get("underlines", [])),
                "box_count": len(geom.get("text_boxes", [])) + len(geom.get("large_boxes", [])),
                "table_cell_count": len(geom.get("table_cells", [])),
                "checkbox_shape_count": len(geom.get("checkbox_candidates", [])),
                "full_text": p.get("full_text", "")[:30000],
            }
        )
    return {
        "page_count": scrape_result.get("page_count", 0),
        "ocr_available": scrape_result.get("ocr_available", False),
        "page_type_counts": scrape_result.get("page_type_counts", {}),
        "pages": pages_summary,
    }


def format_page_scrape_for_vision(page_scrape: Dict[str, Any]) -> str:
    """
    Builds a compact coordinate-indexed summary of Stage 1's scraped text lines and vector
    primitives (using Gemini's 0-1000 [ymin, xmin, ymax, xmax] coordinate space) to ground
    multimodal Vision detection.
    """
    parts: List[str] = []

    lines = page_scrape.get("lines", [])
    if lines:
        line_entries = []
        for ln in lines[:160]:
            y0 = int(round(ln["y_pct"] * 1000))
            x0 = int(round(ln["x_pct"] * 1000))
            y1 = int(round((ln["y_pct"] + ln["h_pct"]) * 1000))
            x1 = int(round((ln["x_pct"] + ln["w_pct"]) * 1000))
            txt = ln["text"].replace("\n", " ")[:120]
            line_entries.append(f"  [{y0},{x0},{y1},{x1}] {txt}")
        parts.append("Scraped Text Lines ([ymin,xmin,ymax,xmax] in 0-1000):\n" + "\n".join(line_entries))

    geom = page_scrape.get("geometry", {})
    cbs = geom.get("checkbox_candidates", [])
    if cbs:
        cb_str = ", ".join(
            f"[{int(round(c['y_pct']*1000))},{int(round(c['x_pct']*1000))},"
            f"{int(round((c['y_pct']+c['h_pct'])*1000))},{int(round((c['x_pct']+c['w_pct'])*1000))}]"
            for c in cbs[:80]
        )
        parts.append(f"Detected Small Checkbox/Radio Shapes: {cb_str}")

    boxes = (geom.get("text_boxes", []) + geom.get("table_cells", []) + geom.get("large_boxes", []))[:80]
    if boxes:
        box_str = ", ".join(
            f"[{int(round(b['y_pct']*1000))},{int(round(b['x_pct']*1000))},"
            f"{int(round((b['y_pct']+b['h_pct'])*1000))},{int(round((b['x_pct']+b['w_pct'])*1000))}]"
            for b in boxes
        )
        parts.append(f"Detected Rectangular Boxes/Cells: {box_str}")

    underlines = geom.get("underlines", [])[:80]
    if underlines:
        ul_str = ", ".join(
            f"[y={int(round(u['y_pct']*1000))}, x={int(round(u['x_pct']*1000))}..{int(round((u['x_pct']+u['w_pct'])*1000))}]"
            for u in underlines
        )
        parts.append(f"Detected Horizontal Underlines: {ul_str}")

    return "\n\n".join(parts) if parts else "No selectable text layer (scanned/image-only page)."

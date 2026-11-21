import io
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from PIL import Image, ImageDraw

from pdf_analyzer import analyze_pdf_document
from pdf_scraper import scrape_pdf_document


def _save_temp_pdf(doc: pymupdf.Document) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


def test_acroform_cryptic_widget_label_resolution():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(45, 115), "Patient Full Name:", fontsize=10, fontname="helv")
    w1 = pymupdf.Widget()
    w1.field_name = "Text1"
    w1.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w1.rect = pymupdf.Rect(165, 100, 460, 122)
    page.add_widget(w1)

    page.insert_text(pymupdf.Point(45, 165), "Allergies / Medical Notes:", fontsize=10, fontname="helv")
    w2 = pymupdf.Widget()
    w2.field_name = "Text2"
    w2.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w2.field_flags = getattr(pymupdf, "PDF_TX_FIELD_IS_MULTILINE", 4096)
    w2.rect = pymupdf.Rect(45, 175, 520, 245)
    page.add_widget(w2)

    w3 = pymupdf.Widget()
    w3.field_name = "CheckBox1"
    w3.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    w3.rect = pymupdf.Rect(45, 280, 60, 295)
    page.add_widget(w3)
    page.insert_text(pymupdf.Point(68, 292), "I consent to treatment", fontsize=10, fontname="helv")

    pdf_path = _save_temp_pdf(doc)
    try:
        res = analyze_pdf_document(pdf_path, use_vision=False)
        assert res["analysis_method"] == "acroform"
        mappings = res["mappings"]
        assert len(mappings) == 3

        by_key = {m["field_key"]: m for m in mappings}
        assert "patient_full_name" in by_key or "full_name" in by_key
        notes_m = next(m for m in mappings if m["type"] == "multiline")
        assert "Allergies" in (notes_m["question_text"] or "")
        cb_m = next(m for m in mappings if m["type"] == "checkbox")
        assert "consent" in (cb_m["question_text"] or "").lower()
    finally:
        os.remove(pdf_path)


def test_flat_vector_multi_layout_qa_detection():
    """Tests underlines, bordered boxes, 2-column table, inline blanks, checkboxes, photo & signature."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text(pymupdf.Point(45, 55), "SECTION A: VISITOR INTAKE", fontsize=12, fontname="hebo")

    # 1. Left-labeled underline
    page.insert_text(pymupdf.Point(45, 100), "Full Name:", fontsize=10, fontname="helv")
    page.draw_line(pymupdf.Point(130, 103), pymupdf.Point(390, 103), color=(0.2, 0.2, 0.2), width=1)

    # 2. Profile photo frame
    page.draw_rect(pymupdf.Rect(445, 65, 545, 180), color=(0.3, 0.3, 0.3), width=1)
    page.insert_text(pymupdf.Point(460, 125), "Attach Photo", fontsize=9, fontname="helv")

    # 3. Bordered empty box with label directly above
    page.insert_text(pymupdf.Point(45, 150), "Reason for Visit:", fontsize=10, fontname="helv")
    page.draw_rect(pymupdf.Rect(45, 158, 390, 215), color=(0.3, 0.3, 0.3), width=1)

    # 4. Vector checkboxes (box to the left of option)
    page.insert_text(pymupdf.Point(45, 255), "Visit Type:", fontsize=10, fontname="helv")
    page.draw_rect(pymupdf.Rect(140, 244, 152, 256), color=(0.2, 0.2, 0.2), width=1)
    page.insert_text(pymupdf.Point(158, 254), "Business", fontsize=9.5, fontname="helv")
    page.draw_rect(pymupdf.Rect(235, 244, 247, 256), color=(0.2, 0.2, 0.2), width=1)
    page.insert_text(pymupdf.Point(253, 254), "Personal", fontsize=9.5, fontname="helv")

    # 5. 2-column table (Label cell | Empty answer cell)
    table_y = [300, 330, 360]
    table_x = [45, 210, 545]
    for yv in table_y:
        page.draw_line(pymupdf.Point(table_x[0], yv), pymupdf.Point(table_x[2], yv), color=(0.3, 0.3, 0.3), width=0.8)
    for xv in table_x:
        page.draw_line(pymupdf.Point(xv, table_y[0]), pymupdf.Point(xv, table_y[2]), color=(0.3, 0.3, 0.3), width=0.8)
    page.insert_text(pymupdf.Point(52, 319), "Host Department", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(52, 349), "Badge Number", fontsize=9.5, fontname="helv")

    # 6. Inline fill-in-the-blank sentence
    page.insert_text(
        pymupdf.Point(45, 420),
        "Passport Country: ______________   Expiry Date: ______________",
        fontsize=10,
        fontname="helv",
    )

    # 7. Signature line with label directly below
    page.draw_line(pymupdf.Point(45, 515), pymupdf.Point(245, 515), color=(0.2, 0.2, 0.2), width=1)
    page.insert_text(pymupdf.Point(45, 528), "Visitor Signature", fontsize=9.5, fontname="helv")

    pdf_path = _save_temp_pdf(doc)
    try:
        res = analyze_pdf_document(pdf_path, use_vision=False)
        assert res["analysis_method"] == "geometry"
        mappings = res["mappings"]
        keys = {m["field_key"] for m in mappings}

        assert "full_name" in keys
        assert "profile_photo" in keys
        assert "reason_for_visit" in keys
        assert "host_department" in keys
        assert "badge_number" in keys
        assert "applicant_signature" in keys

        # Check universal checkboxes grouped under visit_type
        cb_opts = {m["match_value"] for m in mappings if m["type"] == "checkbox" and m["field_key"] == "visit_type"}
        assert {"Business", "Personal"}.issubset(cb_opts)

        # Verify scraped question bounding boxes (qx_pct/qy_pct) are populated for Q->A linking
        with_qbox = [m for m in mappings if m.get("qx_pct") is not None and m.get("qy_pct") is not None]
        assert len(with_qbox) >= 5
    finally:
        os.remove(pdf_path)


def test_multipage_contract_ignores_prose_and_detects_footer_signature():
    doc = pymupdf.open()
    # Page 1: Cover sheet (no form blanks)
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(pymupdf.Point(120, 300), "SERVICE AGREEMENT 2026", fontsize=22, fontname="hebo")
    p1.insert_text(pymupdf.Point(120, 340), "Confidential Document", fontsize=12, fontname="helv")

    # Page 2: Dense prose + footer signature
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text(pymupdf.Point(45, 70), "TERMS AND CONDITIONS", fontsize=12, fontname="hebo")
    p2.insert_text(pymupdf.Point(45, 110), "This agreement governs the delivery of consulting services.", fontsize=10, fontname="helv")
    p2.insert_text(pymupdf.Point(45, 130), "All intellectual property rights remain with the client upon payment.", fontsize=10, fontname="helv")
    p2.insert_text(pymupdf.Point(45, 720), "Authorized Signature:", fontsize=10, fontname="helv")
    p2.draw_line(pymupdf.Point(175, 723), pymupdf.Point(360, 723), color=(0.2, 0.2, 0.2), width=1)

    pdf_path = _save_temp_pdf(doc)
    try:
        scrape = scrape_pdf_document(pdf_path)
        assert scrape["pages"][0]["page_type"] == "prose"

        res = analyze_pdf_document(pdf_path, use_vision=False)
        mappings = res["mappings"]
        assert all(m["page_number"] == 2 for m in mappings)
        assert any(m["type"] == "image" and "signature" in m["field_key"] for m in mappings)
    finally:
        os.remove(pdf_path)


def test_scanned_image_pdf_honest_offline_and_mocked_vision_hybrid():
    """Creates an image-only scanned PDF and tests both offline honesty and mocked Gemini Vision."""
    img = Image.new("RGB", (600, 850), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 560, 100], fill=(20, 35, 65))
    draw.line([(160, 210), (520, 210)], fill=(40, 40, 40), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    pdf_path = _save_temp_pdf(doc)

    try:
        # Offline: should NOT fabricate dummy coordinates
        with patch("pdf_scraper.is_local_ocr_available", return_value=False):
            offline_res = analyze_pdf_document(pdf_path, use_vision=False)
        assert offline_res["analysis_method"] == "scanned_needs_vision"
        assert offline_res["mappings"] == []
        assert any("scanned" in w.lower() for w in offline_res["analysis_summary"]["warnings"])

        # Mocked Gemini Vision call via Interactions API
        fake_vision_json = json.dumps(
            {
                "is_fillable_page": True,
                "page_summary": "Scanned intake form",
                "fields": [
                    {
                        "section": "Applicant Details",
                        "question_text": "Applicant Full Name",
                        "label": "Full name",
                        "field_key": "full_name",
                        "type": "text",
                        "match_value": None,
                        "question_box": [220, 60, 245, 250],
                        "answer_box": [215, 265, 250, 870],
                        "confidence": 0.93,
                    }
                ],
            }
        )

        class FakeInteractions:
            def create(self, **kwargs):
                assert kwargs["store"] is False
                assert kwargs["response_format"]["mime_type"] == "application/json"
                return SimpleNamespace(output_text=fake_vision_json)

        class FakeClient:
            def __init__(self, api_key=None, http_options=None):
                self.interactions = FakeInteractions()

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}),
            patch("pdf_scraper.is_local_ocr_available", return_value=False),
            patch("vision_analyzer.genai.Client", FakeClient),
        ):
            vision_res = analyze_pdf_document(pdf_path, use_vision=True)

        assert vision_res["analysis_method"] == "vision"
        assert len(vision_res["mappings"]) == 1
        m = vision_res["mappings"][0]
        assert m["field_key"] == "full_name"
        assert m["question_text"] == "Applicant Full Name"
        assert m["qx_pct"] == 0.06
        assert m["x_pct"] == 0.265
    finally:
        os.remove(pdf_path)


def test_structured_scrape_extracts_sections_key_values_and_tables():
    """Verifies extraction of structured_sections, key_values, and 2D tables from arbitrary PDFs."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(45, 55), "INVOICE SUMMARY", fontsize=14, fontname="hebo")
    page.insert_text(pymupdf.Point(45, 85), "Invoice Number: INV-2026-091", fontsize=10, fontname="helv")
    page.insert_text(pymupdf.Point(45, 105), "Client Name: Ada Lovelace", fontsize=10, fontname="helv")
    page.insert_text(pymupdf.Point(45, 125), "Empty Field: ________", fontsize=10, fontname="helv")

    page.insert_text(pymupdf.Point(45, 165), "LINE ITEMS", fontsize=12, fontname="hebo")
    xs = [45, 320, 545]
    ys = [180, 210, 240]
    for yv in ys:
        page.draw_line(pymupdf.Point(xs[0], yv), pymupdf.Point(xs[2], yv), color=(0.2, 0.2, 0.2), width=0.8)
    for xv in xs:
        page.draw_line(pymupdf.Point(xv, ys[0]), pymupdf.Point(xv, ys[2]), color=(0.2, 0.2, 0.2), width=0.8)
    page.insert_text(pymupdf.Point(55, 198), "Item", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(330, 198), "Total", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(55, 228), "Architecture Audit", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(330, 228), "$1,500", fontsize=9.5, fontname="helv")

    pdf_path = _save_temp_pdf(doc)
    try:
        scrape = scrape_pdf_document(pdf_path)
        pg = scrape["pages"][0]
        kvs = {kv["key"]: kv["value"] for kv in pg["key_values"]}
        assert kvs["Invoice Number"] == "INV-2026-091"
        assert kvs["Client Name"] == "Ada Lovelace"
        assert "Empty Field" not in kvs

        assert len(pg["tables"]) == 1
        assert pg["tables"][0] == [
            ["Item", "Total"],
            ["Architecture Audit", "$1,500"],
        ]

        sec_titles = [s["title"] for s in pg["structured_sections"]]
        assert "INVOICE SUMMARY" in sec_titles
        assert "LINE ITEMS" in sec_titles
    finally:
        os.remove(pdf_path)


def test_offline_parenthetical_checkboxes_and_wrapped_table_labels():
    """Verifies parenthetical (  ) checkboxes, trailing Why/Date fields, and wrapped table label dedupe."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    xs = [45, 250, 550]
    ys = [90, 140, 185, 230]
    for yv in ys:
        page.draw_line(pymupdf.Point(xs[0], yv), pymupdf.Point(xs[2], yv), color=(0.2, 0.2, 0.2), width=0.8)
    for xv in xs:
        page.draw_line(pymupdf.Point(xv, ys[0]), pymupdf.Point(xv, ys[3]), color=(0.2, 0.2, 0.2), width=0.8)

    # Row 1: Wrapped 2-line question on left, empty answer cell on right
    page.insert_text(pymupdf.Point(52, 110), "Role Applied For/", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(52, 125), "Knowledge Track:", fontsize=9.5, fontname="helv")

    # Row 2: Experience level with parenthetical blanks
    page.insert_text(pymupdf.Point(52, 165), "Experience Level?", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(260, 165), "None(  ) Beginner(  ) Intermediate(  )", fontsize=9.0, fontname="helv")

    # Row 3: Yes/No + trailing Why:
    page.insert_text(pymupdf.Point(52, 210), "Available Today?", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(260, 210), "Yes (  ) No (  ) Why:", fontsize=9.0, fontname="helv")

    pdf_path = _save_temp_pdf(doc)
    try:
        res = analyze_pdf_document(pdf_path, use_vision=False)
        mappings = res["mappings"]

        # Wrapped label must NOT produce a duplicate fragment field "knowledge_track"
        text_keys = [m["field_key"] for m in mappings if m["type"] in ("text", "multiline")]
        assert "knowledge_track" not in text_keys
        assert any("role_applied_for" in k for k in text_keys)

        # Experience level options grouped under one field_key
        exp_opts = {
            m["match_value"]
            for m in mappings
            if m["type"] == "checkbox" and "experience" in m["field_key"]
        }
        assert exp_opts == {"None", "Beginner", "Intermediate"}

        # Yes/No + trailing Why field extracted cleanly
        avail_opts = {
            m["match_value"]
            for m in mappings
            if m["type"] == "checkbox" and "available" in m["field_key"]
        }
        assert avail_opts == {"Yes", "No"}
        assert any("why" in m["field_key"] for m in mappings if m["type"] == "text")
    finally:
        os.remove(pdf_path)


def test_vision_checkbox_unification_none_recovery_and_readonly_skip():
    """
    Verifies:
      1. Split Vision checkbox keys sharing a label unify into one field_key.
      2. Coerced null match_value recovers literal "None" from page text.
      3. When Vision returns is_fillable_page=False, Stage 4 offline geometry does NOT fabricate fields.
    """
    # Part A: Read-only Resume-like document (has underline + colon cue, so Stage 1 marks digital_flat)
    doc_ro = pymupdf.open()
    p_ro = doc_ro.new_page(width=595, height=842)
    p_ro.insert_text(pymupdf.Point(45, 70), "PROFESSIONAL SUMMARY", fontsize=13, fontname="hebo")
    p_ro.insert_text(pymupdf.Point(45, 100), "Languages: Python, TypeScript", fontsize=10, fontname="helv")
    p_ro.draw_line(pymupdf.Point(45, 110), pymupdf.Point(545, 110), color=(0.2, 0.2, 0.2), width=1)
    ro_path = _save_temp_pdf(doc_ro)

    class ReadOnlyInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "is_fillable_page": False,
                        "page_summary": "A read-only resume document.",
                        "extracted_key_values": [{"key": "Languages", "value": "Python, TypeScript"}],
                        "scanned_text": None,
                        "fields": [],
                    }
                )
            )

    class ReadOnlyClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = ReadOnlyInteractions()

    try:
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
            patch("vision_analyzer.genai.Client", ReadOnlyClient),
        ):
            ro_res = analyze_pdf_document(ro_path, use_vision=True)

        assert ro_res["mappings"] == []
        assert ro_res["analysis_method"] == "vision_readonly"
        assert ro_res["scraped_storage"]["pages"][0]["page_summary"] == "A read-only resume document."
    finally:
        os.remove(ro_path)

    # Part B: Vision checkbox unification & "None" option recovery
    doc_cb = pymupdf.open()
    p_cb = doc_cb.new_page(width=595, height=842)
    p_cb.insert_text(pymupdf.Point(45, 120), "Experience: None(  ) Beginner(  ) Advanced(  )", fontsize=10, fontname="helv")
    p_cb.insert_text(pymupdf.Point(45, 220), "Team Experience: Yes (  ) No (  )", fontsize=10, fontname="helv")
    cb_path = _save_temp_pdf(doc_cb)

    class CheckboxInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "is_fillable_page": True,
                        "page_summary": "Questionnaire with checkboxes.",
                        "extracted_key_values": [],
                        "scanned_text": None,
                        "fields": [
                            {
                                "section": "Background",
                                "question_text": "Experience Level",
                                "label": "Experience Level",
                                "field_key": "experience_level",
                                "type": "checkbox",
                                "match_value": None,
                                "question_box": [130, 75, 155, 200],
                                "answer_box": [132, 230, 152, 250],
                                "confidence": 0.9,
                            },
                            {
                                "section": "Background",
                                "question_text": "Experience Level",
                                "label": "Experience Level",
                                "field_key": "experience_level",
                                "type": "checkbox",
                                "match_value": "Beginner",
                                "question_box": [130, 75, 155, 200],
                                "answer_box": [132, 330, 152, 350],
                                "confidence": 0.9,
                            },
                            {
                                "section": "Background",
                                "question_text": "Team Experience",
                                "label": "Team Experience",
                                "field_key": "team_experience_yes",
                                "type": "checkbox",
                                "match_value": "Yes",
                                "question_box": [250, 75, 275, 240],
                                "answer_box": [250, 280, 270, 300],
                                "confidence": 0.9,
                            },
                            {
                                "section": "Background",
                                "question_text": "Team Experience",
                                "label": "Team Experience",
                                "field_key": "team_experience_no",
                                "type": "checkbox",
                                "match_value": "No",
                                "question_box": [250, 75, 275, 240],
                                "answer_box": [250, 350, 270, 370],
                                "confidence": 0.9,
                            },
                        ],
                    }
                )
            )

    class CheckboxClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = CheckboxInteractions()

    try:
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
            patch("vision_analyzer.genai.Client", CheckboxClient),
        ):
            cb_res = analyze_pdf_document(cb_path, use_vision=True)

        mappings = cb_res["mappings"]
        exp_m = [m for m in mappings if m["label"] == "Experience Level"]
        assert {m["match_value"] for m in exp_m} == {"None", "Beginner"}

        team_m = [m for m in mappings if m["label"] == "Team Experience"]
        assert len({m["field_key"] for m in team_m}) == 1
        assert {m["match_value"] for m in team_m} == {"Yes", "No"}
    finally:
        os.remove(cb_path)

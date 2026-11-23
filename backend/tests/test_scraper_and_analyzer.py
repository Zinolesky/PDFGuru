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


def test_rawdict_paren_snapping_recovers_large_vision_drift_and_scanned_contours():
    """
    Verifies:
      1. Stage 1 `rawdict` parenthetical slot centers snap Vision checkboxes even with ~47pt horizontal drift.
      2. Scanned image-only pages snap Vision checkbox predictions onto hollow square contours.
    """
    # Part A: Digital PDF with `(  )` slots + severe horizontal Vision drift on Intermediate
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    row_txt = "None(  ) Beginner(  ) Intermediate(  ) Advanced(  )"
    page.insert_text(pymupdf.Point(290, 375), row_txt, fontsize=10.5, fontname="helv")
    pdf_path = _save_temp_pdf(doc)

    # Extract true rawdict slot centers directly via Stage 1
    from pdf_scraper import scrape_pdf_document

    scrape = scrape_pdf_document(pdf_path)
    paren_cands = [
        c for c in scrape["pages"][0]["geometry"]["checkbox_candidates"] if c.get("source") == "text_paren"
    ]
    assert [c.get("label_before") for c in paren_cands] == ["None", "Beginner", "Intermediate", "Advanced"]
    true_by_label = {c["label_before"]: c for c in paren_cands}

    class DriftedVisionInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "is_fillable_page": True,
                        "page_summary": "Questionnaire with parenthetical checkboxes.",
                        "extracted_key_values": [],
                        "scanned_text": None,
                        "fields": [
                            {
                                "section": "Profile",
                                "question_text": "Experience Level?",
                                "label": "Experience Level",
                                "field_key": "experience_level",
                                "type": "checkbox",
                                "match_value": None,
                                "question_box": [450, 80, 480, 260],
                                "answer_box": [460, 505, 476, 520],
                                "confidence": 0.85,
                            },
                            {
                                "section": "Profile",
                                "question_text": "Experience Level?",
                                "label": "Experience Level",
                                "field_key": "experience_level",
                                "type": "checkbox",
                                "match_value": "Beginner",
                                "question_box": [450, 80, 480, 260],
                                "answer_box": [460, 575, 476, 590],
                                "confidence": 0.85,
                            },
                            {
                                "section": "Profile",
                                "question_text": "Experience Level?",
                                "label": "Experience Level",
                                "field_key": "experience_level",
                                "type": "checkbox",
                                "match_value": "Intermediate",
                                "question_box": [450, 80, 480, 260],
                                # Deliberate ~0.078 (~47pt) horizontal drift left!
                                "answer_box": [
                                    460,
                                    int(round((true_by_label["Intermediate"]["cx_pct"] - 0.08) * 1000)),
                                    476,
                                    int(round((true_by_label["Intermediate"]["cx_pct"] - 0.072) * 1000)),
                                ],
                                "confidence": 0.85,
                            },
                        ],
                    }
                )
            )

    class DriftedClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = DriftedVisionInteractions()

    try:
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
            patch("vision_analyzer.genai.Client", DriftedClient),
        ):
            res = analyze_pdf_document(pdf_path, use_vision=True)

        assert res["analysis_method"] == "vision_hybrid"
        by_mv = {m["match_value"]: m for m in res["mappings"] if m["type"] == "checkbox"}
        for opt in ("None", "Beginner", "Intermediate"):
            m = by_mv[opt]
            assert m["detection_source"] == "vision_snapped"
            assert m["width_pct"] and m["height_pct"]
            assert abs(m["x_pct"] - true_by_label[opt]["cx_pct"]) < 0.001
            assert abs(m["y_pct"] - true_by_label[opt]["cy_pct"]) < 0.001
    finally:
        os.remove(pdf_path)

    # Part B: Scanned image-only page with hollow square box at (240..256, 200..216) on 600x850 px
    img = Image.new("RGB", (600, 850), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([240, 200, 256, 216], outline=(20, 20, 20), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    sdoc = pymupdf.open()
    sp = sdoc.new_page(width=600, height=850)
    sp.insert_image(sp.rect, stream=buf.getvalue())
    scan_path = _save_temp_pdf(sdoc)

    # True center: x=248/600=0.4133, y=208/850=0.2447; mock shifted by ~10pt
    class ScannedBoxInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "is_fillable_page": True,
                        "page_summary": "Scanned form with square box.",
                        "extracted_key_values": [],
                        "scanned_text": "Agree",
                        "fields": [
                            {
                                "section": None,
                                "question_text": "Agree",
                                "label": "Agree",
                                "field_key": "agree",
                                "type": "checkbox",
                                "match_value": "Yes",
                                "question_box": [235, 120, 255, 200],
                                "answer_box": [228, 385, 248, 405],
                                "confidence": 0.84,
                            }
                        ],
                    }
                )
            )

    class ScannedClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = ScannedBoxInteractions()

    try:
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
            patch("vision_analyzer.genai.Client", ScannedClient),
        ):
            sres = analyze_pdf_document(scan_path, use_vision=True)

        assert len(sres["mappings"]) == 1
        sm = sres["mappings"][0]
        assert sm["detection_source"] == "vision_snapped"
        assert abs(sm["x_pct"] - (248.0 / 600.0)) < 0.004
        assert abs(sm["y_pct"] - (208.0 / 850.0)) < 0.004
    finally:
        os.remove(scan_path)


def test_followup_key_non_collision_and_full_question_enrichment():
    """
    Verifies:
      1. Long (>48-char) checkbox questions produce distinct, non-colliding follow-up `field_key`s
         without mid-word chopping (`Soft`), and carry full parent `question_text`.
      2. Vision analysis recovers skipped trailing inline follow-up text fields (`What/Where?`)
         and strips raw `Yes ( ) No ( )` option clutter while prepending the parent question.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    xs = [45, 275, 550]
    ys = [90, 145, 200]
    for yv in ys:
        page.draw_line(pymupdf.Point(xs[0], yv), pymupdf.Point(xs[2], yv), color=(0.2, 0.2, 0.2), width=0.8)
    for xv in xs:
        page.draw_line(pymupdf.Point(xv, ys[0]), pymupdf.Point(xv, ys[2]), color=(0.2, 0.2, 0.2), width=0.8)

    page.insert_text(pymupdf.Point(52, 112), "Have you been part of a Software", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(52, 126), "Development Team?", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(285, 118), "Yes (  ) No (  ) What/Where?", fontsize=9.5, fontname="helv")

    page.insert_text(pymupdf.Point(52, 172), "Have you completed NYSC?", fontsize=9.5, fontname="helv")
    page.insert_text(pymupdf.Point(285, 172), "Yes (  ) No (  ) NYSC Date:", fontsize=9.5, fontname="helv")

    pdf_path = _save_temp_pdf(doc)

    try:
        # Part A: Offline geometry guarantees unique keys + full parent context
        off_res = analyze_pdf_document(pdf_path, use_vision=False)
        off_cbs = [m for m in off_res["mappings"] if m["type"] == "checkbox"]
        off_txts = [m for m in off_res["mappings"] if m["type"] == "text"]
        cb_keys = {m["field_key"] for m in off_cbs}
        txt_keys = {m["field_key"] for m in off_txts}
        assert cb_keys.isdisjoint(txt_keys)

        ww_field = next(m for m in off_txts if "what" in (m.get("question_text") or "").lower())
        assert "Soft (" not in ww_field["label"]
        assert "software development team?" in ww_field["question_text"].lower()
        assert "what/where" in ww_field["question_text"].lower()

        # Part B: Vision misses "What/Where?" and emits cluttered "Yes ( ) No ( ) NYSC Date"
        class PartialVisionInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    output_text=json.dumps(
                        {
                            "is_fillable_page": True,
                            "page_summary": "Questionnaire table.",
                            "extracted_key_values": [],
                            "scanned_text": None,
                            "fields": [
                                {
                                    "section": None,
                                    "question_text": "Have you been part of a Software Development Team?",
                                    "label": "Software Development Team",
                                    "field_key": "software_development_team",
                                    "type": "checkbox",
                                    "match_value": "Yes",
                                    "question_box": [120, 85, 155, 440],
                                    "answer_box": [130, 515, 146, 535],
                                    "confidence": 0.9,
                                },
                                {
                                    "section": None,
                                    "question_text": "Have you been part of a Software Development Team?",
                                    "label": "Software Development Team",
                                    "field_key": "software_development_team",
                                    "type": "checkbox",
                                    "match_value": "No",
                                    "question_box": [120, 85, 155, 440],
                                    "answer_box": [130, 565, 146, 585],
                                    "confidence": 0.9,
                                },
                                {
                                    "section": None,
                                    "question_text": "Have you completed NYSC?",
                                    "label": "NYSC completed",
                                    "field_key": "nysc_completed",
                                    "type": "checkbox",
                                    "match_value": "Yes",
                                    "question_box": [195, 85, 215, 440],
                                    "answer_box": [196, 515, 212, 535],
                                    "confidence": 0.9,
                                },
                                {
                                    "section": None,
                                    "question_text": "Have you completed NYSC?",
                                    "label": "NYSC completed",
                                    "field_key": "nysc_completed",
                                    "type": "checkbox",
                                    "match_value": "No",
                                    "question_box": [195, 85, 215, 440],
                                    "answer_box": [196, 565, 212, 585],
                                    "confidence": 0.9,
                                },
                                {
                                    "section": None,
                                    "question_text": "Yes (  ) No (  ) NYSC Date:",
                                    "label": "Yes (  ) No (  ) NYSC Date",
                                    "field_key": "nysc_date",
                                    "type": "text",
                                    "match_value": None,
                                    "question_box": [195, 600, 215, 720],
                                    "answer_box": [195, 725, 218, 910],
                                    "confidence": 0.85,
                                },
                            ],
                        }
                    )
                )

        class PartialVisionClient:
            def __init__(self, api_key=None, http_options=None):
                self.interactions = PartialVisionInteractions()

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
            patch("vision_analyzer.genai.Client", PartialVisionClient),
        ):
            vis_res = analyze_pdf_document(pdf_path, use_vision=True)

        vis_maps = vis_res["mappings"]
        vis_txts = [m for m in vis_maps if m["type"] == "text"]
        ww_vis = next(
            m
            for m in vis_txts
            if "software development team" in m["question_text"].lower()
            and "what/where" in m["question_text"].lower()
        )
        team_cb_idx = max(
            i
            for i, m in enumerate(vis_maps)
            if m["type"] == "checkbox" and m["field_key"] == "software_development_team"
        )
        assert team_cb_idx < vis_maps.index(ww_vis)

        nysc_date = next(m for m in vis_txts if m["field_key"] == "nysc_date")
        nysc_cb_idx = max(
            i
            for i, m in enumerate(vis_maps)
            if m["type"] == "checkbox" and "nysc" in m["field_key"]
        )
        assert nysc_cb_idx < vis_maps.index(nysc_date)
        assert "yes (" not in nysc_date["label"].lower()
        assert "yes (" not in nysc_date["question_text"].lower()
        assert "have you completed nysc?" in nysc_date["question_text"].lower()
        assert "nysc date" in nysc_date["question_text"].lower()
    finally:
        os.remove(pdf_path)


def test_conditional_followup_links_to_matching_option_and_abstains_safely():
    """
    Verifies:
      1. When two checkbox questions share one horizontal row (Radio/Others on left, Yes/No on right),
         a next-line 'If Yes, Project Name & Location:' follow-up links to the Yes/No question
         rather than the closer Radio/Others checkbox — both without and with explicit parent_field_key.
      2. When no upward checkbox group has an option matching 'If Yes', enrichment safely abstains
         instead of attaching an incompatible parent question.
    """
    from pdf_analyzer import _enrich_field_questions_and_followups

    page_scrape = {
        "page_number": 3,
        "page_type": "scanned_image",
        "lines": [],
        "sections": [],
        "geometry": {"table_cells": []},
    }

    def _build_two_question_row_mappings(explicit_parent=None):
        return [
            {
                "type": "checkbox",
                "field_key": "how_did_you_know",
                "label": "How did you get to know?",
                "question_text": "How did you get to know about LEKKI AVANA SIGNATURE?",
                "match_value": "Radio",
                "x_pct": 0.117,
                "y_pct": 0.286,
                "page_number": 3,
            },
            {
                "type": "checkbox",
                "field_key": "how_did_you_know",
                "label": "How did you get to know?",
                "question_text": "How did you get to know about LEKKI AVANA SIGNATURE?",
                "match_value": "Others",
                "x_pct": 0.229,
                "y_pct": 0.286,
                "page_number": 3,
            },
            {
                "type": "checkbox",
                "field_key": "own_zylus_property",
                "label": "Own Zylus property",
                "question_text": "Do you own any property with Zylus homes and Property?",
                "match_value": "Yes",
                "x_pct": 0.747,
                "y_pct": 0.286,
                "page_number": 3,
            },
            {
                "type": "checkbox",
                "field_key": "own_zylus_property",
                "label": "Own Zylus property",
                "question_text": "Do you own any property with Zylus homes and Property?",
                "match_value": "No",
                "x_pct": 0.866,
                "y_pct": 0.286,
                "page_number": 3,
            },
            {
                "type": "text",
                "field_key": "project_name_and_location",
                "label": "Project Name & Location",
                "question_text": "If Yes, Project Name & Location:",
                "match_value": None,
                "_parent_field_key": explicit_parent,
                "x_pct": 0.287,
                "y_pct": 0.297,
                "width_pct": 0.65,
                "height_pct": 0.018,
                "page_number": 3,
            },
        ]

    # Case 1A: Heuristic fallback when Vision omits parent_field_key
    res_heur = _enrich_field_questions_and_followups(_build_two_question_row_mappings(None), page_scrape)
    followup_heur = next(m for m in res_heur if m["field_key"] == "project_name_and_location")
    assert "_parent_field_key" not in followup_heur
    assert "do you own any property with zylus homes and property?" in followup_heur["question_text"].lower()
    assert "if yes, project name & location" in followup_heur["question_text"].lower()
    assert "how did you get to know" not in followup_heur["question_text"].lower()

    # Case 1B: Explicit Vision parent_field_key
    res_exp = _enrich_field_questions_and_followups(
        _build_two_question_row_mappings("own_zylus_property"),
        page_scrape,
    )
    followup_exp = next(m for m in res_exp if m["field_key"] == "project_name_and_location")
    assert "do you own any property" in followup_exp["question_text"].lower()

    # Case 2: Safe abstention when only Radio/Others exists above an "If Yes" prompt
    incompat_only = [
        m for m in _build_two_question_row_mappings(None) if m["field_key"] != "own_zylus_property"
    ]
    res_abstain = _enrich_field_questions_and_followups(incompat_only, page_scrape)
    followup_abstain = next(m for m in res_abstain if m["field_key"] == "project_name_and_location")
    assert followup_abstain["question_text"] == "If Yes, Project Name & Location:"


def test_scanned_currency_obstacle_trims_figures_box_right_of_symbol():
    """
    Verifies `_trim_boxes_around_inline_obstacles` trims a wide single-line figures field
    crossing a central scanned currency symbol (e.g. '________ ₦ ________') so writing
    starts strictly after the symbol while clean single-line underlines remain untouched.
    """
    from vision_analyzer import _trim_boxes_around_inline_obstacles

    img_w, img_h = 1000, 1400
    img = Image.new("L", (img_w, img_h), color=255)
    draw = ImageDraw.Draw(img)

    # Row 1: clean single underline for words box (no interior tall ink)
    draw.rectangle([160, 972, 940, 974], fill=20)

    # Row 2: left underline + bold central currency symbol + right underline
    draw.rectangle([60, 1016, 495, 1018], fill=20)
    draw.rectangle([545, 1016, 940, 1018], fill=20)
    # Draw bold central N-with-bars glyph spanning x=508..532, y=990..1018
    draw.rectangle([508, 990, 513, 1018], fill=10)
    draw.rectangle([527, 990, 532, 1018], fill=10)
    draw.line([(510, 992), (530, 1016)], fill=10, width=4)
    draw.rectangle([505, 1001, 535, 1004], fill=10)
    draw.rectangle([505, 1007, 535, 1010], fill=10)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    page_scrape = {"page_number": 3, "page_type": "scanned_image", "lines": []}
    results = [
        {
            "type": "text",
            "field_key": "total_cost_words",
            "label": "Total Cost amount in word",
            "question_text": "Total Cost:",
            "x_pct": 0.16,
            "y_pct": 0.681,
            "width_pct": 0.782,
            "height_pct": 0.018,
            "detection_source": "vision",
        },
        {
            "type": "text",
            "field_key": "total_cost_figures",
            "label": "Total Cost amount in figures",
            "question_text": "Total Cost Amount:",
            "x_pct": 0.061,
            "y_pct": 0.711,
            "width_pct": 0.882,
            "height_pct": 0.018,
            "detection_source": "vision",
        },
    ]

    trimmed = _trim_boxes_around_inline_obstacles(results, page_scrape, png_bytes=png_bytes)
    words_m = next(m for m in trimmed if m["field_key"] == "total_cost_words")
    figs_m = next(m for m in trimmed if m["field_key"] == "total_cost_figures")

    assert words_m["x_pct"] == 0.16
    assert words_m["width_pct"] == 0.782
    assert figs_m["x_pct"] > 0.525
    assert figs_m["width_pct"] < 0.45
    assert figs_m["detection_source"] == "vision_snapped"


def test_inline_dotted_agreement_blank_over_150_chars_extracted_cleanly():
    """
    Verifies Stage 4 offline Step 6a catches long (>150 chars) declaration/undertaking
    dotted leaders (e.g. `I/we...........a subscriber...`) with a clean contextual label.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(210, 80), "AGREEMENT & UNDERTAKING", fontsize=12, fontname="hebo")
    agreement_line = (
        "I/we"
        + ("." * 115)
        + "a subscriber to the Lekki Avana Signature do hereby acknowledge my obligation."
    )
    assert len(agreement_line) > 150
    page.insert_text(pymupdf.Point(45, 130), agreement_line, fontsize=8.5, fontname="helv")
    page.insert_text(pymupdf.Point(340, 220), "Subscriber's signature: ______________", fontsize=9.5, fontname="helv")
    pdf_path = _save_temp_pdf(doc)

    try:
        res = analyze_pdf_document(pdf_path, use_vision=False)
        mappings = res["mappings"]
        sub_name = next((m for m in mappings if m["field_key"] == "subscriber_full_name"), None)
        assert sub_name is not None
        assert sub_name["label"] == "Subscriber full name"
        assert "subscriber" in sub_name["question_text"].lower()
        assert "[___]" in sub_name["question_text"]
        assert sub_name["width_pct"] >= 0.06
    finally:
        os.remove(pdf_path)

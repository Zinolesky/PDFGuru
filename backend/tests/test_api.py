import io
import json
import os
import tempfile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

# Use isolated temp DB and deterministic offline mode during tests
os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix="_pdfguru_test.db")
os.close(_tmp_db_fd)
os.environ["PDFGURU_DB_PATH"] = _tmp_db_path

import main  # noqa: E402
from main import UPLOADS_DIR, app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
    main.engine.dispose()
    if os.path.exists(_tmp_db_path):
        try:
            os.remove(_tmp_db_path)
        except OSError:
            pass


def _make_sample_png_bytes(width: int = 240, height: int = 120) -> bytes:
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.line([(20, 80), (100, 40), (180, 75), (220, 50)], fill=(15, 25, 90), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_sample_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(50, 70), "UNIVERSAL INTAKE FORM", fontsize=14, fontname="hebo")
    page.insert_text(pymupdf.Point(50, 125), "First Name:", fontsize=10, fontname="helv")
    page.draw_line(pymupdf.Point(140, 128), pymupdf.Point(400, 128), color=(0.3, 0.3, 0.3), width=1)
    page.insert_text(pymupdf.Point(50, 165), "Last Name:", fontsize=10, fontname="helv")
    page.draw_line(pymupdf.Point(140, 168), pymupdf.Point(400, 168), color=(0.3, 0.3, 0.3), width=1)
    page.insert_text(pymupdf.Point(50, 215), "Company Stamp:", fontsize=10, fontname="helv")
    page.draw_rect(pymupdf.Rect(160, 200, 270, 275), color=(0.3, 0.3, 0.3), width=1)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_health_check(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "PDFGuru" in data["service"]
    assert "gemini_model" in data
    assert "gemini_vision_model" in data
    assert "local_ocr_available" in data


def test_seeded_universal_templates_and_scraped_content(client: TestClient):
    res = client.get("/api/templates")
    assert res.status_code == 200
    templates = res.json()
    # Both the flat General Application Form and the AcroForm Sample should be seeded
    assert len(templates) >= 2
    methods = {t["analysis_method"] for t in templates}
    assert "geometry" in methods
    assert "acroform" in methods

    template_id = templates[0]["id"]
    dict_res = client.get(f"/api/templates/{template_id}/dictionary-format")
    assert dict_res.status_code == 200
    dict_data = dict_res.json()
    assert dict_data["template_id"] == template_id
    assert len(dict_data["fields"]) >= 10
    assert "First name:" in dict_data["blank_dictionary_text"]

    scraped_res = client.get(f"/api/templates/{template_id}/scraped-content")
    assert scraped_res.status_code == 200
    scraped = scraped_res.json()
    assert len(scraped["pages"]) == templates[0]["page_count"]
    assert "GENERAL APPLICATION" in scraped["pages"][0]["full_text"]


def test_parse_dictionary_endpoint(client: TestClient):
    raw_text = (
        "First name: Jordan\n"
        "Last name: Rivera\n"
        "Email address: jordan@example.com\n"
        "Department: Engineering\n"
    )
    res = client.post("/api/parse-dictionary", json={"raw_text": raw_text})
    assert res.status_code == 200
    body = res.json()
    assert body["parser_used"] == "dictionary-heuristic"
    fields = body["fields"]
    assert fields["first_name"] == "Jordan"
    assert fields["last_name"] == "Rivera"
    assert fields["full_name"] == "Jordan Rivera"
    assert fields["email"] == "jordan@example.com"
    assert fields["department"] == "Engineering"


def test_process_image_preview_signature_and_photo(client: TestClient):
    png_bytes = _make_sample_png_bytes()

    sig_res = client.post(
        "/api/process-image-preview",
        data={"mode": "signature", "threshold": "205", "rotate_deg": "90"},
        files={"image_file": ("sig.png", png_bytes, "image/png")},
    )
    assert sig_res.status_code == 200
    assert sig_res.headers["content-type"] == "image/png"
    assert sig_res.content.startswith(b"\x89PNG")

    photo_res = client.post(
        "/api/process-image-preview",
        data={"mode": "photo", "rotate_deg": "0", "smart_crop": "true"},
        files={"image_file": ("photo.png", png_bytes, "image/png")},
    )
    assert photo_res.status_code == 200
    assert photo_res.content.startswith(b"\x89PNG")


def test_profiles_crud_lifecycle(client: TestClient):
    create_res = client.post(
        "/api/profiles",
        json={"name": "Jordan Profile", "data": {"first_name": "Jordan", "email": "jordan@example.com"}},
    )
    assert create_res.status_code == 200
    prof = create_res.json()
    prof_id = prof["id"]
    assert prof["name"] == "Jordan Profile"

    list_res = client.get("/api/profiles")
    assert list_res.status_code == 200
    assert any(p["id"] == prof_id for p in list_res.json())

    upd_res = client.put(
        f"/api/profiles/{prof_id}",
        json={"name": "Jordan Updated", "data": {"first_name": "Jordan", "city": "Toronto"}},
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["data"]["city"] == "Toronto"

    del_res = client.delete(f"/api/profiles/{prof_id}")
    assert del_res.status_code == 200


def test_upload_duplicate_same_page_mappings_generate_and_disk_cleanup(client: TestClient):
    pdf_bytes = _make_sample_pdf_bytes()
    upload_res = client.post(
        "/api/templates",
        data={"document_name": "CI Universal Form", "auto_analyze": "true", "use_vision": "false"},
        files={"pdf_file": ("ci_universal_form.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 200
    created = upload_res.json()
    template_id = created["id"]
    pdf_filename = created["pdf_filename"]
    assert created["name"] == "CI Universal Form"
    assert os.path.exists(os.path.join(UPLOADS_DIR, pdf_filename))

    try:
        # Persist two identical field_keys on the same page + a custom image slot
        mappings_payload = [
            {
                "type": "text",
                "field_key": "first_name",
                "label": "First name",
                "question_text": "First Name:",
                "x_pct": 0.24,
                "y_pct": 0.13,
                "width_pct": 0.42,
                "height_pct": 0.025,
                "page_number": 1,
                "font_size": 10.5,
            },
            {
                "type": "text",
                "field_key": "first_name",
                "label": "First name",
                "question_text": "Repeated First Name:",
                "x_pct": 0.24,
                "y_pct": 0.18,
                "width_pct": 0.42,
                "height_pct": 0.025,
                "page_number": 1,
                "font_size": 10.5,
            },
            {
                "type": "image",
                "field_key": "company_stamp",
                "label": "Company stamp",
                "x_pct": 0.27,
                "y_pct": 0.24,
                "width_pct": 0.18,
                "height_pct": 0.09,
                "page_number": 1,
            },
        ]
        save_res = client.put(f"/api/templates/{template_id}/mappings", json=mappings_payload)
        assert save_res.status_code == 200
        assert len(save_res.json()) == 3

        # Generate stamped PDF with dynamic image_slot__company_stamp
        stamp_png = _make_sample_png_bytes()
        gen_res = client.post(
            "/api/generate-pdf",
            data={
                "template_id": str(template_id),
                "form_data": json.dumps({"first_name": "Adaeze"}),
                "image_slots_meta": json.dumps(
                    {"company_stamp": {"mode": "signature", "rotate_deg": 90, "threshold": 205}}
                ),
            },
            files={"image_slot__company_stamp": ("stamp.png", stamp_png, "image/png")},
        )
        assert gen_res.status_code == 200
        assert gen_res.headers["content-type"] == "application/pdf"
        assert gen_res.content.startswith(b"%PDF-")

        out_doc = pymupdf.open(stream=gen_res.content, filetype="pdf")
        assert out_doc[0].get_text("text").count("Adaeze") == 2
        assert len(out_doc[0].get_images()) == 1
        out_doc.close()
    finally:
        del_res = client.delete(f"/api/templates/{template_id}")
        assert del_res.status_code == 200
        # Verify uploaded PDF file was cleaned up from disk
        assert not os.path.exists(os.path.join(UPLOADS_DIR, pdf_filename))


def test_optional_access_token_middleware(client: TestClient):
    os.environ["PDFGURU_ACCESS_TOKEN"] = "secret-test-token"
    try:
        # Health stays open
        assert client.get("/api/health").status_code == 200
        # Protected route rejects missing token
        assert client.get("/api/templates").status_code == 401
        # Accepts X-API-Key or Bearer token
        assert client.get("/api/templates", headers={"X-API-Key": "secret-test-token"}).status_code == 200
        assert (
            client.get("/api/templates", headers={"Authorization": "Bearer secret-test-token"}).status_code
            == 200
        )
    finally:
        os.environ.pop("PDFGURU_ACCESS_TOKEN", None)


def test_generate_pdf_mapping_overrides_non_destructive(client: TestClient):
    """Verifies per-request `mapping_overrides` moves stamped output without mutating saved template rows."""
    tpls = client.get("/api/templates").json()
    assert tpls
    tpl = next((t for t in tpls if t.get("mappings")), tpls[0])
    target_m = next(m for m in tpl["mappings"] if m["type"] in ("text", "multiline"))
    orig_x = target_m["x_pct"]
    orig_y = target_m["y_pct"]

    overrides = {
        str(target_m["id"]): {
            "x_pct": 0.45,
            "y_pct": 0.72,
            "width_pct": 0.30,
            "height_pct": 0.03,
        }
    }
    res = client.post(
        "/api/generate-pdf",
        data={
            "template_id": str(tpl["id"]),
            "form_data": json.dumps({target_m["field_key"]: "OVERRIDE_POS_CHECK"}),
            "mapping_overrides": json.dumps(overrides),
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"

    out_doc = pymupdf.open(stream=res.content, filetype="pdf")
    page_idx = max(0, (target_m.get("page_number") or 1) - 1)
    page = out_doc[page_idx]
    hits = page.search_for("OVERRIDE_POS_CHECK")
    assert hits
    r = hits[0]
    pw, ph = float(page.rect.width), float(page.rect.height)
    out_doc.close()

    assert abs((r.x0 / pw) - 0.45) < 0.03
    assert abs((r.y0 / ph) - 0.72) < 0.04

    # Original template coordinates in DB remain untouched
    after_tpl = client.get(f"/api/templates/{tpl['id']}").json()
    after_m = next(m for m in after_tpl["mappings"] if m["id"] == target_m["id"])
    assert after_m["x_pct"] == pytest.approx(orig_x, abs=1e-4)
    assert after_m["y_pct"] == pytest.approx(orig_y, abs=1e-4)


def test_missing_pdf_templates_excluded_and_dictionary_has_questions(client: TestClient):
    """Verifies templates whose PDF is missing on disk are hidden and every field carries `question_text`."""
    pdf_bytes = _make_sample_pdf_bytes()
    upload_res = client.post(
        "/api/templates",
        data={"document_name": "Zombie Check Doc", "auto_analyze": "true", "use_vision": "false"},
        files={"pdf_file": ("zombie_check.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 200
    created = upload_res.json()
    tid = created["id"]
    pdf_disk_path = os.path.join(UPLOADS_DIR, created["pdf_filename"])

    try:
        # Dictionary format carries non-empty question_text on every detected field
        dict_res = client.get(f"/api/templates/{tid}/dictionary-format")
        assert dict_res.status_code == 200
        fields = dict_res.json()["fields"]
        assert fields
        assert all((f.get("question_text") or "").strip() for f in fields)

        # Simulate orphaned DB row after PDF file deletion on disk
        if os.path.exists(pdf_disk_path):
            os.remove(pdf_disk_path)
        list_ids = [t["id"] for t in client.get("/api/templates").json()]
        assert tid not in list_ids
    finally:
        client.delete(f"/api/templates/{tid}")

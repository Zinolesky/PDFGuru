import base64
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anyio
import pymupdf
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from ai_service import get_text_model_name, parse_input_text
from models import (
    DictionaryFormatResponse,
    DocumentTemplate,
    DocumentTemplateRead,
    FieldMapping,
    FieldMappingCreate,
    FieldMappingRead,
    ParseTextRequest,
    ParseTextResponse,
    ProfileCreate,
    ProfileRead,
    SavedProfile,
    ScrapedContentResponse,
    UniversalFormData,
)
from pdf_analyzer import (
    analyze_pdf_document,
    build_dictionary_format_from_mappings,
    humanize_key,
)
from pdf_scraper import is_local_ocr_available
from pdf_service import process_photo_image, process_signature_transparency, stamp_pdf
from seed import seed_database
from vision_analyzer import get_gemini_api_key, get_vision_model_name

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

DB_PATH = os.getenv("DOCUFILL_DB_PATH") or os.path.join(BASE_DIR, "docufill.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

MAX_PDF_BYTES = int(os.getenv("MAX_PDF_MB", "25")) * 1024 * 1024
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_MB", "10")) * 1024 * 1024

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def get_session():
    with Session(engine) as session:
        yield session


def _ensure_sqlite_columns() -> None:
    """Non-destructive schema evolution for existing SQLite databases."""
    migrations = [
        "ALTER TABLE documenttemplate ADD COLUMN analysis_method VARCHAR",
        "ALTER TABLE documenttemplate ADD COLUMN analysis_summary_json VARCHAR",
        "ALTER TABLE documenttemplate ADD COLUMN scraped_content_json VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN label VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN question_text VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN section VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN qx_pct FLOAT",
        "ALTER TABLE fieldmapping ADD COLUMN qy_pct FLOAT",
        "ALTER TABLE fieldmapping ADD COLUMN qw_pct FLOAT",
        "ALTER TABLE fieldmapping ADD COLUMN qh_pct FLOAT",
        "ALTER TABLE fieldmapping ADD COLUMN align VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN confidence FLOAT",
        "ALTER TABLE fieldmapping ADD COLUMN detection_source VARCHAR",
        "ALTER TABLE fieldmapping ADD COLUMN acroform_field_name VARCHAR",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass


def _serialize_template(template: DocumentTemplate) -> DocumentTemplateRead:
    summary = None
    if template.analysis_summary_json:
        try:
            summary = json.loads(template.analysis_summary_json)
        except Exception:
            summary = None
    return DocumentTemplateRead(
        id=template.id,
        name=template.name,
        pdf_filename=template.pdf_filename,
        page_count=template.page_count,
        analysis_method=template.analysis_method,
        analysis_summary=summary,
        created_at=template.created_at,
        mappings=[FieldMappingRead.model_validate(m) for m in (template.mappings or [])],
    )


def _persist_detected_mappings(
    session: Session, template_id: int, detected: List[Dict[str, Any]]
) -> None:
    for m in detected:
        row = FieldMapping(
            template_id=template_id,
            type=m.get("type") or "text",
            field_key=m["field_key"],
            label=m.get("label") or humanize_key(m["field_key"]),
            question_text=m.get("question_text"),
            section=m.get("section"),
            match_value=m.get("match_value"),
            x_pct=max(0.0, min(1.0, float(m["x_pct"]))),
            y_pct=max(0.0, min(1.0, float(m["y_pct"]))),
            width_pct=max(0.0, min(1.0, float(m["width_pct"]))) if m.get("width_pct") is not None else None,
            height_pct=max(0.0, min(1.0, float(m["height_pct"]))) if m.get("height_pct") is not None else None,
            qx_pct=max(0.0, min(1.0, float(m["qx_pct"]))) if m.get("qx_pct") is not None else None,
            qy_pct=max(0.0, min(1.0, float(m["qy_pct"]))) if m.get("qy_pct") is not None else None,
            qw_pct=max(0.0, min(1.0, float(m["qw_pct"]))) if m.get("qw_pct") is not None else None,
            qh_pct=max(0.0, min(1.0, float(m["qh_pct"]))) if m.get("qh_pct") is not None else None,
            page_number=int(m.get("page_number") or 1),
            font_size=float(m["font_size"]) if m.get("font_size") is not None else None,
            align=m.get("align") or "left",
            confidence=float(m["confidence"]) if m.get("confidence") is not None else 1.0,
            detection_source=m.get("detection_source") or "geometry",
            acroform_field_name=m.get("acroform_field_name"),
        )
        session.add(row)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_columns()
    with Session(engine) as session:
        seed_database(session, UPLOADS_DIR)
    yield


app = FastAPI(
    title="DocuFill AI — Universal PDF Scraper & Form Filler",
    description="Upload any PDF document, scrape its full content, detect questions and answer regions, generate a copyable Key:Value format, and stamp completed PDFs.",
    version="3.0.0",
    lifespan=lifespan,
)

# Configurable CORS (never mixes wildcard '*' with allow_credentials=True)
raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
).strip()
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
is_wildcard = allowed_origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=not is_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_access_token_middleware(request: Request, call_next):
    """Enforces optional DOCUFILL_ACCESS_TOKEN on /api/* endpoints (except /api/health) when set."""
    expected_token = os.getenv("DOCUFILL_ACCESS_TOKEN", "").strip()
    if expected_token and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if request.method != "OPTIONS":
            auth_hdr = request.headers.get("authorization", "")
            bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
            provided = request.headers.get("x-api-key", "").strip() or bearer
            if provided != expected_token:
                return JSONResponse(status_code=401, content={"detail": "Invalid or missing access token"})
    return await call_next(request)


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "DocuFill AI Universal PDF Backend",
        "gemini_model": get_text_model_name(),
        "gemini_vision_model": get_vision_model_name(),
        "gemini_key_configured": bool(get_gemini_api_key()),
        "local_ocr_available": is_local_ocr_available(),
    }


@app.get("/api/templates", response_model=List[DocumentTemplateRead])
def list_templates(session: Session = Depends(get_session)):
    templates = session.exec(select(DocumentTemplate).order_by(DocumentTemplate.id)).all()
    return [_serialize_template(t) for t in templates]


@app.get("/api/templates/{template_id}", response_model=DocumentTemplateRead)
def get_template(template_id: int, session: Session = Depends(get_session)):
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")
    return _serialize_template(template)


@app.get("/api/templates/{template_id}/scraped-content", response_model=ScrapedContentResponse)
def get_template_scraped_content(template_id: int, session: Session = Depends(get_session)):
    """Returns the full scraped page text, section headings, and geometry diagnostics for any uploaded PDF."""
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")

    scraped_pages: List[Dict[str, Any]] = []
    if template.scraped_content_json:
        try:
            parsed = json.loads(template.scraped_content_json)
            scraped_pages = parsed.get("pages", [])
        except Exception:
            scraped_pages = []

    summary = None
    if template.analysis_summary_json:
        try:
            summary = json.loads(template.analysis_summary_json)
        except Exception:
            summary = None

    return ScrapedContentResponse(
        template_id=template.id,
        document_name=template.name,
        page_count=template.page_count,
        analysis_method=template.analysis_method,
        analysis_summary=summary,
        pages=scraped_pages,
    )


@app.get("/api/templates/{template_id}/dictionary-format", response_model=DictionaryFormatResponse)
def get_template_dictionary_format(
    template_id: int,
    session: Session = Depends(get_session),
):
    """Generates the authoritative field list and copyable Key: Value dictionary format."""
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")
    mappings = session.exec(
        select(FieldMapping).where(FieldMapping.template_id == template_id)
    ).all()
    return build_dictionary_format_from_mappings(
        template_id=template.id,
        document_name=template.name,
        page_count=template.page_count,
        mappings=list(mappings),
        analysis_method=template.analysis_method,
    )


@app.post("/api/templates", response_model=DocumentTemplateRead)
async def create_template(
    document_name: Optional[str] = Form(None),
    auto_analyze: bool = Form(True),
    use_vision: bool = Form(True),
    pdf_file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """
    Uploads ANY PDF document, scrapes its full content & vector geometry, detects questions
    and answer locations (AcroForm -> Gemini 4 Vision + Geometry Snapping -> Offline Vector Engine),
    and returns the ready-to-fill document template.
    """
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document")

    pdf_bytes = await pdf_file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF file exceeds maximum allowed size of {MAX_PDF_BYTES // (1024 * 1024)} MB",
        )

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        doc.close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PDF file: {exc}")

    doc_title = (document_name or "").strip()
    if not doc_title:
        base = os.path.splitext(os.path.basename(pdf_file.filename))[0]
        doc_title = re.sub(r"[_\-]+", " ", base).strip() or "Uploaded PDF Document"

    clean_orig = re.sub(r"[^a-zA-Z0-9._\-]", "_", os.path.basename(pdf_file.filename))
    safe_filename = f"{uuid.uuid4().hex[:10]}_{clean_orig}"
    filepath = os.path.join(UPLOADS_DIR, safe_filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    analysis_method = "manual"
    analysis_summary_json = None
    scraped_content_json = None
    detected_mappings: List[Dict[str, Any]] = []

    try:
        if auto_analyze:
            analysis = await anyio.to_thread.run_sync(
                lambda: analyze_pdf_document(filepath, use_vision=use_vision)
            )
            detected_mappings = analysis["mappings"]
            analysis_method = analysis["analysis_method"]
            analysis_summary_json = json.dumps(analysis["analysis_summary"])
            scraped_content_json = json.dumps(analysis["scraped_storage"])

        template = DocumentTemplate(
            name=doc_title,
            pdf_filename=safe_filename,
            page_count=page_count,
            analysis_method=analysis_method,
            analysis_summary_json=analysis_summary_json,
            scraped_content_json=scraped_content_json,
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        if detected_mappings:
            _persist_detected_mappings(session, template.id, detected_mappings)
            session.commit()
            session.refresh(template)
    except Exception:
        session.rollback()
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        raise

    return _serialize_template(template)


@app.post("/api/templates/{template_id}/analyze", response_model=DocumentTemplateRead)
async def analyze_existing_template(
    template_id: int,
    use_vision: bool = True,
    session: Session = Depends(get_session),
):
    """Re-scrapes and re-analyzes an uploaded PDF document, refreshing its detected Q->A mappings."""
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")
    pdf_path = os.path.join(UPLOADS_DIR, template.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file missing on disk")

    analysis = await anyio.to_thread.run_sync(
        lambda: analyze_pdf_document(pdf_path, use_vision=use_vision)
    )

    existing = session.exec(
        select(FieldMapping).where(FieldMapping.template_id == template_id)
    ).all()
    for item in existing:
        session.delete(item)
    session.commit()

    template.analysis_method = analysis["analysis_method"]
    template.analysis_summary_json = json.dumps(analysis["analysis_summary"])
    template.scraped_content_json = json.dumps(analysis["scraped_storage"])
    session.add(template)
    _persist_detected_mappings(session, template.id, analysis["mappings"])
    session.commit()
    session.refresh(template)
    return _serialize_template(template)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int, session: Session = Depends(get_session)):
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")

    pdf_filename = template.pdf_filename
    session.delete(template)
    session.commit()

    # Clean up uploaded PDF file if no other template references it
    still_used = session.exec(
        select(DocumentTemplate).where(DocumentTemplate.pdf_filename == pdf_filename)
    ).first()
    if not still_used:
        pdf_path = os.path.join(UPLOADS_DIR, pdf_filename)
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                pass

    return {"deleted": True, "id": template_id}


@app.get("/api/templates/{template_id}/pdf")
def get_template_pdf(template_id: int, session: Session = Depends(get_session)):
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")
    pdf_path = os.path.join(UPLOADS_DIR, template.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    return FileResponse(pdf_path, media_type="application/pdf", filename=template.pdf_filename)


@app.get("/api/templates/{template_id}/page-image/{page_number}")
def get_template_page_image(
    template_id: int, page_number: int = 1, session: Session = Depends(get_session)
):
    """High-DPI PNG fallback render of a PDF page using PyMuPDF (sync -> runs in worker threadpool)."""
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")
    pdf_path = os.path.join(UPLOADS_DIR, template.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    doc = pymupdf.open(pdf_path)
    idx = max(0, min(len(doc) - 1, page_number - 1))
    page = doc[idx]
    scale = 1200.0 / max(1.0, float(page.rect.width))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    png_bytes = pix.tobytes("png")
    doc.close()
    return Response(content=png_bytes, media_type="image/png")


@app.put("/api/templates/{template_id}/mappings", response_model=List[FieldMappingRead])
def save_template_mappings(
    template_id: int,
    mappings: List[FieldMappingCreate],
    session: Session = Depends(get_session),
):
    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")

    existing = session.exec(
        select(FieldMapping).where(FieldMapping.template_id == template_id)
    ).all()
    for item in existing:
        session.delete(item)
    session.commit()

    saved: List[FieldMapping] = []
    for m in mappings:
        row = FieldMapping(
            template_id=template_id,
            type=m.type,
            field_key=m.field_key,
            label=m.label or humanize_key(m.field_key),
            question_text=m.question_text,
            section=m.section,
            match_value=m.match_value,
            x_pct=max(0.0, min(1.0, m.x_pct)),
            y_pct=max(0.0, min(1.0, m.y_pct)),
            width_pct=max(0.0, min(1.0, m.width_pct)) if m.width_pct is not None else None,
            height_pct=max(0.0, min(1.0, m.height_pct)) if m.height_pct is not None else None,
            qx_pct=max(0.0, min(1.0, m.qx_pct)) if m.qx_pct is not None else None,
            qy_pct=max(0.0, min(1.0, m.qy_pct)) if m.qy_pct is not None else None,
            qw_pct=max(0.0, min(1.0, m.qw_pct)) if m.qw_pct is not None else None,
            qh_pct=max(0.0, min(1.0, m.qh_pct)) if m.qh_pct is not None else None,
            page_number=m.page_number or 1,
            font_size=m.font_size if m.font_size is not None else (10.0 if m.type in ("text", "multiline") else None),
            align=m.align or "left",
            confidence=m.confidence if m.confidence is not None else 1.0,
            detection_source=m.detection_source or "manual",
            acroform_field_name=m.acroform_field_name,
        )
        session.add(row)
        saved.append(row)

    session.commit()
    for row in saved:
        session.refresh(row)
    return saved


@app.post("/api/parse-dictionary", response_model=ParseTextResponse)
@app.post("/api/parse-text", response_model=ParseTextResponse)
def parse_text_endpoint(
    payload: ParseTextRequest,
    session: Session = Depends(get_session),
) -> ParseTextResponse:
    """
    Parses filled Key: Value dictionary text or unstructured messages into field values
    matching the active PDF document's detected inputs and checkbox options.
    """
    if not payload.raw_text or not payload.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text is required")

    expected_fields = payload.expected_fields
    if not expected_fields and payload.template_id:
        template = session.get(DocumentTemplate, payload.template_id)
        if template:
            mappings = session.exec(
                select(FieldMapping).where(FieldMapping.template_id == payload.template_id)
            ).all()
            spec = build_dictionary_format_from_mappings(
                template_id=template.id,
                document_name=template.name,
                page_count=template.page_count,
                mappings=list(mappings),
                analysis_method=template.analysis_method,
            )
            expected_fields = [f.model_dump() for f in spec.fields if f.type != "image"]

    return parse_input_text(payload.raw_text, expected_fields=expected_fields)


def _decode_data_url_or_base64(b64_str: Optional[str]) -> Optional[bytes]:
    if not b64_str:
        return None
    if "," in b64_str and b64_str.strip().startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    return base64.b64decode(b64_str)


@app.post("/api/process-image-preview")
async def process_image_preview_endpoint(
    image_file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    mode: str = Form("signature"),  # "signature" | "photo"
    threshold: int = Form(205),
    rotate_deg: int = Form(0),
    smart_crop: bool = Form(True),
):
    upload = image_file or image
    if not upload:
        raise HTTPException(status_code=400, detail="Missing image file")
    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty image file")
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds maximum allowed size of {MAX_IMAGE_BYTES // (1024 * 1024)} MB",
        )
    try:
        if mode in ("photo", "passport"):
            out_bytes = await anyio.to_thread.run_sync(
                lambda: process_photo_image(raw_bytes, rotate_deg=rotate_deg, smart_crop=smart_crop)
            )
        else:
            out_bytes = await anyio.to_thread.run_sync(
                lambda: process_signature_transparency(raw_bytes, threshold=threshold, rotate_deg=rotate_deg)
            )
        return Response(content=out_bytes, media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Image processing failed: {exc}")


@app.post("/api/generate-pdf")
async def generate_pdf_endpoint(
    request: Request,
    session: Session = Depends(get_session),
):
    content_type = request.headers.get("content-type", "")
    image_slots: Dict[str, Dict[str, Any]] = {}
    passport_bytes: Optional[bytes] = None
    signature_bytes: Optional[bytes] = None
    witness_signature_bytes: Optional[bytes] = None
    signature_threshold: int = 205
    passport_rotate: int = 0
    signature_rotate: int = 0
    witness_signature_rotate: int = 0
    passport_smart_crop: bool = True

    if "application/json" in content_type:
        body = await request.json()
        template_id = int(body.get("template_id"))
        raw_form = body.get("form_data", {})
        if isinstance(raw_form, str):
            raw_form = json.loads(raw_form)
        form_data = UniversalFormData(**raw_form)
        passport_bytes = _decode_data_url_or_base64(
            body.get("photo_image_base64") or body.get("passport_image_base64") or body.get("passport_image")
        )
        signature_bytes = _decode_data_url_or_base64(
            body.get("signature_image_base64") or body.get("signature_image")
        )
        witness_signature_bytes = _decode_data_url_or_base64(
            body.get("witness_signature_image_base64") or body.get("witness_signature_image")
        )
        signature_threshold = int(body.get("signature_threshold", 205))
        passport_rotate = int(body.get("passport_rotate", 0))
        signature_rotate = int(body.get("signature_rotate", 0))
        witness_signature_rotate = int(body.get("witness_signature_rotate", 0))
        passport_smart_crop = bool(body.get("passport_smart_crop", True))

        # Support arbitrary dynamic image slots in JSON: body["images"] = {field_key: {data_url, mode, rotate_deg, ...}}
        raw_images = body.get("images") or {}
        if isinstance(raw_images, dict):
            for slot_key, cfg in raw_images.items():
                if isinstance(cfg, dict) and cfg.get("data"):
                    img_b = _decode_data_url_or_base64(cfg["data"])
                    if img_b:
                        image_slots[slot_key] = {
                            "bytes": img_b,
                            "mode": cfg.get("mode", "signature"),
                            "rotate_deg": int(cfg.get("rotate_deg", 0)),
                            "threshold": int(cfg.get("threshold", signature_threshold)),
                            "smart_crop": bool(cfg.get("smart_crop", True)),
                        }
    else:
        form = await request.form()
        template_id = int(form.get("template_id"))
        raw_form_str = form.get("form_data", "{}")
        form_data_dict = json.loads(raw_form_str) if isinstance(raw_form_str, str) else raw_form_str
        form_data = UniversalFormData(**form_data_dict)

        if form.get("signature_threshold") is not None:
            signature_threshold = int(form.get("signature_threshold"))
        if form.get("passport_rotate") is not None:
            passport_rotate = int(form.get("passport_rotate"))
        if form.get("signature_rotate") is not None:
            signature_rotate = int(form.get("signature_rotate"))
        if form.get("witness_signature_rotate") is not None:
            witness_signature_rotate = int(form.get("witness_signature_rotate"))
        if form.get("passport_smart_crop") is not None:
            passport_smart_crop = str(form.get("passport_smart_crop")).lower() not in ("false", "0")

        # Parse dynamic slot metadata JSON: {"slot_key": {"mode": "photo"|"signature", "rotate_deg": 90, "threshold": 205, "smart_crop": true}}
        slot_meta_map: Dict[str, Dict[str, Any]] = {}
        raw_slot_meta = form.get("image_slots_meta")
        if isinstance(raw_slot_meta, str) and raw_slot_meta.strip():
            try:
                slot_meta_map = json.loads(raw_slot_meta)
            except Exception:
                slot_meta_map = {}

        # Read any dynamic `image_slot__<field_key>` uploaded files
        for form_key, val in form.multi_items():
            if form_key.startswith("image_slot__"):
                slot_key = form_key[len("image_slot__") :]
                if hasattr(val, "read"):
                    img_b = await val.read()
                    if img_b:
                        if len(img_b) > MAX_IMAGE_BYTES:
                            raise HTTPException(status_code=413, detail=f"Image for '{slot_key}' exceeds size limit")
                        meta = slot_meta_map.get(slot_key, {})
                        image_slots[slot_key] = {
                            "bytes": img_b,
                            "mode": meta.get("mode"),
                            "rotate_deg": int(meta.get("rotate_deg", 0)),
                            "threshold": int(meta.get("threshold", signature_threshold)),
                            "smart_crop": bool(meta.get("smart_crop", True)),
                        }

        # Backwards-compatible named image uploads
        async def _read_optional_upload(key_name: str) -> Optional[bytes]:
            item = form.get(key_name)
            if item and hasattr(item, "read"):
                b = await item.read()
                if b and len(b) > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail=f"Image '{key_name}' exceeds size limit")
                return b or None
            if isinstance(item, str) and item:
                return _decode_data_url_or_base64(item)
            return None

        passport_bytes = await _read_optional_upload("passport_image") or await _read_optional_upload("photo_image")
        signature_bytes = await _read_optional_upload("signature_image")
        witness_signature_bytes = await _read_optional_upload("witness_signature_image")

    template = session.get(DocumentTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Document template not found")

    pdf_path = os.path.join(UPLOADS_DIR, template.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Template PDF file not found on disk")

    mappings = session.exec(
        select(FieldMapping).where(FieldMapping.template_id == template_id)
    ).all()

    stamped_bytes = await anyio.to_thread.run_sync(
        lambda: stamp_pdf(
            pdf_path=pdf_path,
            mappings=list(mappings),
            form_data=form_data,
            image_slots=image_slots,
            passport_bytes=passport_bytes,
            signature_bytes=signature_bytes,
            witness_signature_bytes=witness_signature_bytes,
            signature_threshold=signature_threshold,
            passport_rotate=passport_rotate,
            signature_rotate=signature_rotate,
            witness_signature_rotate=witness_signature_rotate,
            passport_smart_crop=passport_smart_crop,
        )
    )

    fd_dict = form_data.model_dump()
    safe_doc = re.sub(r"[^a-zA-Z0-9_\-]", "_", template.name.replace("—", "-"))
    person_label = (
        fd_dict.get("last_name")
        or fd_dict.get("surname")
        or fd_dict.get("first_name")
        or fd_dict.get("full_name")
        or "Completed"
    )
    safe_person = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(person_label).replace(" ", "_"))
    filename = f"DocuFill_{safe_doc}_{safe_person}.pdf"

    return Response(
        content=stamped_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


# =============================================================================
# SAVED DATA PROFILES (REUSABLE ACROSS ANY PDF DOCUMENT)
# =============================================================================
@app.get("/api/profiles", response_model=List[ProfileRead])
def list_profiles(session: Session = Depends(get_session)):
    rows = session.exec(select(SavedProfile).order_by(SavedProfile.updated_at.desc())).all()
    out: List[ProfileRead] = []
    for r in rows:
        try:
            d = json.loads(r.data_json or "{}")
        except Exception:
            d = {}
        out.append(
            ProfileRead(
                id=r.id,
                name=r.name,
                data=d,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


@app.post("/api/profiles", response_model=ProfileRead)
def create_profile(payload: ProfileCreate, session: Session = Depends(get_session)):
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    now = datetime.now(timezone.utc)
    clean_data = {k: v for k, v in (payload.data or {}).items() if v is not None and str(v).strip() != ""}
    row = SavedProfile(
        name=clean_name,
        data_json=json.dumps(clean_data),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return ProfileRead(
        id=row.id,
        name=row.name,
        data=clean_data,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.put("/api/profiles/{profile_id}", response_model=ProfileRead)
def update_profile(profile_id: int, payload: ProfileCreate, session: Session = Depends(get_session)):
    row = session.get(SavedProfile, profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    clean_data = {k: v for k, v in (payload.data or {}).items() if v is not None and str(v).strip() != ""}
    row.name = clean_name
    row.data_json = json.dumps(clean_data)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return ProfileRead(
        id=row.id,
        name=row.name,
        data=clean_data,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, session: Session = Depends(get_session)):
    row = session.get(SavedProfile, profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    session.delete(row)
    session.commit()
    return {"deleted": True, "id": profile_id}


@app.get("/api/samples/{asset_name}")
def get_sample_asset(asset_name: str):
    allowed = {
        "photo": "sample_photo.png",
        "passport": "sample_photo.png",
        "signature": "sample_signature.png",
        "witness_signature": "sample_witness_signature.png",
    }
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="Sample asset not found")
    path = os.path.join(UPLOADS_DIR, "samples", allowed[asset_name])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sample file not generated yet")
    return FileResponse(path, media_type="image/png")

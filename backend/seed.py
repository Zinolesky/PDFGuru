import json
import os
import re
import shutil
import pymupdf
from PIL import Image, ImageDraw
from sqlmodel import Session, select

from models import DocumentTemplate, FieldMapping
from pdf_analyzer import analyze_pdf_document, humanize_key


def create_sample_assets(samples_dir: str) -> None:
    """Generates clean demo profile photo, signature, and witness signature PNGs."""
    os.makedirs(samples_dir, exist_ok=True)

    photo_path = os.path.join(samples_dir, "sample_photo.png")
    if not os.path.exists(photo_path):
        img = Image.new("RGB", (350, 450), color=(234, 240, 248))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 349, 449], outline=(195, 208, 224), width=4)
        # Shoulders & torso
        draw.pieslice([45, 285, 305, 515], 180, 360, fill=(28, 45, 82))
        draw.polygon([(145, 295), (175, 355), (205, 295)], fill=(255, 255, 255))
        draw.polygon([(170, 325), (175, 420), (180, 325)], fill=(185, 42, 42))
        # Neck & head silhouette
        draw.rectangle([148, 240, 202, 305], fill=(158, 114, 86))
        draw.ellipse([108, 92, 242, 256], fill=(166, 120, 90))
        draw.pieslice([104, 80, 246, 182], 180, 360, fill=(28, 24, 22))
        draw.ellipse([142, 160, 156, 174], fill=(24, 22, 20))
        draw.ellipse([194, 160, 208, 174], fill=(24, 22, 20))
        draw.arc([152, 198, 198, 226], 15, 165, fill=(75, 38, 28), width=4)
        img.save(photo_path, format="PNG")

    sig_path = os.path.join(samples_dir, "sample_signature.png")
    if not os.path.exists(sig_path):
        sig = Image.new("RGB", (500, 180), color=(244, 242, 236))
        sdraw = ImageDraw.Draw(sig)
        points = [
            (40, 130), (65, 55), (90, 125), (118, 68), (135, 118),
            (175, 85), (210, 112), (245, 60), (270, 115), (315, 92),
            (360, 108), (410, 75), (455, 95),
        ]
        sdraw.line(points, fill=(15, 32, 95), width=5, joint="curve")
        sdraw.line([(55, 145), (260, 132), (445, 124)], fill=(15, 32, 95), width=4)
        sig.save(sig_path, format="PNG")

    witness_sig_path = os.path.join(samples_dir, "sample_witness_signature.png")
    if not os.path.exists(witness_sig_path):
        wsig = Image.new("RGB", (500, 180), color=(246, 245, 240))
        wdraw = ImageDraw.Draw(wsig)
        wpoints = [
            (50, 115), (85, 48), (110, 122), (150, 72), (195, 105),
            (235, 65), (275, 110), (330, 82), (390, 98), (440, 70),
        ]
        wdraw.line(wpoints, fill=(20, 25, 45), width=5, joint="curve")
        wdraw.line([(70, 138), (420, 128)], fill=(20, 25, 45), width=3)
        wsig.save(witness_sig_path, format="PNG")


def _create_general_application_pdf(pdf_path: str) -> None:
    """
    Creates a clean 2-page universal flat PDF form showcasing underlines, bordered boxes,
    checkboxes, a photo frame, multiline notes, and signature/date lines.
    """
    if os.path.exists(pdf_path):
        return
    doc = pymupdf.open()

    # --- PAGE 1 ---
    page = doc.new_page(width=595, height=842)
    page.draw_rect(
        pymupdf.Rect(36, 30, 559, 86),
        color=(0.08, 0.14, 0.28),
        fill=(0.08, 0.14, 0.28),
    )
    page.insert_text(
        pymupdf.Point(52, 56),
        "GENERAL APPLICATION & REGISTRATION FORM",
        fontsize=13,
        fontname="helv",
        color=(1, 1, 1),
    )
    page.insert_text(
        pymupdf.Point(52, 74),
        "Complete all sections below and attach a profile photo & signature",
        fontsize=8.5,
        fontname="helv",
        color=(0.82, 0.88, 0.96),
    )

    # Profile photo box on top-right
    page.draw_rect(pymupdf.Rect(455, 102, 555, 224), color=(0.35, 0.4, 0.5), width=1.2)
    page.insert_text(
        pymupdf.Point(473, 166),
        "Profile Photo",
        fontsize=9,
        fontname="helv",
        color=(0.45, 0.5, 0.58),
    )

    page.insert_text(
        pymupdf.Point(45, 112),
        "SECTION 1: PERSONAL INFORMATION",
        fontsize=10,
        fontname="hebo",
        color=(0.08, 0.14, 0.28),
    )

    rows = [
        ("First name:", 140, 435),
        ("Last name:", 175, 435),
        ("Date of birth:", 210, 435),
        ("Nationality:", 248, 555),
        ("Email address:", 285, 555),
        ("Phone number:", 322, 555),
        ("Residential address:", 359, 555),
        ("City:", 396, 285),
        ("Country:", 433, 285),
    ]
    for label_txt, y_val, line_end_x in rows:
        page.insert_text(
            pymupdf.Point(45, y_val),
            label_txt,
            fontsize=10,
            fontname="helv",
            color=(0.12, 0.16, 0.24),
        )
        page.draw_line(
            pymupdf.Point(185, y_val + 3),
            pymupdf.Point(line_end_x, y_val + 3),
            color=(0.55, 0.62, 0.72),
            width=0.9,
        )

    # Checkboxes: Gender & Contact Preference
    page.insert_text(pymupdf.Point(45, 478), "Gender:", fontsize=10, fontname="helv")
    page.draw_rect(pymupdf.Rect(185, 467, 197, 479), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(203, 477), "Male", fontsize=9.5, fontname="helv")
    page.draw_rect(pymupdf.Rect(258, 467, 270, 479), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(276, 477), "Female", fontsize=9.5, fontname="helv")
    page.draw_rect(pymupdf.Rect(342, 467, 354, 479), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(360, 477), "Other", fontsize=9.5, fontname="helv")

    page.insert_text(pymupdf.Point(45, 514), "Preferred Contact:", fontsize=10, fontname="helv")
    page.draw_rect(pymupdf.Rect(185, 503, 197, 515), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(203, 513), "Email", fontsize=9.5, fontname="helv")
    page.draw_rect(pymupdf.Rect(258, 503, 270, 515), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(276, 513), "Phone", fontsize=9.5, fontname="helv")
    page.draw_rect(pymupdf.Rect(342, 503, 354, 515), color=(0.25, 0.3, 0.4), width=1)
    page.insert_text(pymupdf.Point(360, 513), "SMS", fontsize=9.5, fontname="helv")

    # Section 2: Employment & Emergency Contact
    page.insert_text(
        pymupdf.Point(45, 560),
        "SECTION 2: ORGANIZATION & EMERGENCY CONTACT",
        fontsize=10,
        fontname="hebo",
        color=(0.08, 0.14, 0.28),
    )
    rows2 = [
        ("Occupation / Job title:", 592, 555),
        ("Employer / Organization:", 628, 555),
        ("Emergency contact name:", 664, 555),
        ("Emergency contact phone:", 700, 555),
    ]
    for label_txt, y_val, line_end_x in rows2:
        page.insert_text(
            pymupdf.Point(45, y_val),
            label_txt,
            fontsize=10,
            fontname="helv",
            color=(0.12, 0.16, 0.24),
        )
        page.draw_line(
            pymupdf.Point(195, y_val + 3),
            pymupdf.Point(line_end_x, y_val + 3),
            color=(0.55, 0.62, 0.72),
            width=0.9,
        )

    # Signature & Date at bottom of Page 1
    page.insert_text(pymupdf.Point(45, 768), "Applicant signature:", fontsize=10, fontname="helv")
    page.draw_line(pymupdf.Point(170, 772), pymupdf.Point(350, 772), color=(0.3, 0.35, 0.45), width=1)
    page.insert_text(pymupdf.Point(385, 768), "Date:", fontsize=10, fontname="helv")
    page.draw_line(pymupdf.Point(425, 772), pymupdf.Point(555, 772), color=(0.3, 0.35, 0.45), width=1)

    # --- PAGE 2 ---
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text(
        pymupdf.Point(45, 58),
        "SECTION 3: ADDITIONAL NOTES & DECLARATION",
        fontsize=11,
        fontname="hebo",
        color=(0.08, 0.14, 0.28),
    )
    page2.insert_text(
        pymupdf.Point(45, 92),
        "Additional Notes or Special Requests:",
        fontsize=10,
        fontname="helv",
    )
    page2.draw_rect(pymupdf.Rect(45, 102, 555, 220), color=(0.45, 0.5, 0.6), width=1)

    page2.insert_text(
        pymupdf.Point(45, 270),
        "I confirm that the information provided in this document is accurate and complete.",
        fontsize=9.5,
        fontname="helv",
        color=(0.25, 0.28, 0.35),
    )
    page2.insert_text(pymupdf.Point(45, 325), "Full name:", fontsize=10, fontname="helv")
    page2.draw_line(pymupdf.Point(130, 328), pymupdf.Point(555, 328), color=(0.55, 0.62, 0.72), width=0.9)

    page2.insert_text(pymupdf.Point(45, 390), "Applicant signature:", fontsize=10, fontname="helv")
    page2.draw_line(pymupdf.Point(170, 394), pymupdf.Point(350, 394), color=(0.3, 0.35, 0.45), width=1)
    page2.insert_text(pymupdf.Point(385, 390), "Date:", fontsize=10, fontname="helv")
    page2.draw_line(pymupdf.Point(425, 394), pymupdf.Point(555, 394), color=(0.3, 0.35, 0.45), width=1)

    doc.save(pdf_path)
    doc.close()


def _create_interactive_acroform_sample_pdf(pdf_path: str) -> None:
    """Creates a clean 1-page interactive AcroForm PDF sample for instant AcroForm testing."""
    if os.path.exists(pdf_path):
        return
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    page.draw_rect(
        pymupdf.Rect(36, 32, 559, 82),
        color=(0.06, 0.28, 0.24),
        fill=(0.06, 0.28, 0.24),
    )
    page.insert_text(
        pymupdf.Point(52, 62),
        "INTERACTIVE ONBOARDING & CONSENT FORM (ACROFORM)",
        fontsize=12.5,
        fontname="helv",
        color=(1, 1, 1),
    )

    fields = [
        ("full_name", "Full name", 125, 190, 540, 22),
        ("email", "Email address", 168, 190, 540, 22),
        ("phone_number", "Phone number", 211, 190, 420, 22),
        ("department", "Department", 254, 190, 420, 22),
        ("start_date", "Start date", 297, 190, 360, 22),
    ]
    for f_name, label, y_val, x0, x1, h in fields:
        page.insert_text(pymupdf.Point(48, y_val + 15), f"{label}:", fontsize=10, fontname="helv")
        w = pymupdf.Widget()
        w.field_name = f_name
        w.field_label = label
        w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        w.rect = pymupdf.Rect(x0, y_val, x1, y_val + h)
        w.border_color = (0.4, 0.45, 0.55)
        w.fill_color = (0.97, 0.98, 1.0)
        page.add_widget(w)

    # Checkboxes
    page.insert_text(pymupdf.Point(48, 362), "Work Mode:", fontsize=10, fontname="helv")
    for idx, (cb_name, cb_label, cx) in enumerate(
        [("remote_work", "Remote", 190), ("hybrid_work", "Hybrid", 290), ("onsite_work", "On-site", 390)]
    ):
        w = pymupdf.Widget()
        w.field_name = cb_name
        w.field_label = cb_label
        w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        w.rect = pymupdf.Rect(cx, 350, cx + 14, 364)
        w.border_color = (0.3, 0.35, 0.45)
        page.add_widget(w)
        page.insert_text(pymupdf.Point(cx + 20, 362), cb_label, fontsize=9.5, fontname="helv")

    # Multiline bio/comments widget
    page.insert_text(pymupdf.Point(48, 412), "Additional comments:", fontsize=10, fontname="helv")
    mw = pymupdf.Widget()
    mw.field_name = "additional_comments"
    mw.field_label = "Additional comments"
    mw.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    mw.field_flags = getattr(pymupdf, "PDF_TX_FIELD_IS_MULTILINE", 4096)
    mw.rect = pymupdf.Rect(48, 422, 540, 515)
    mw.border_color = (0.4, 0.45, 0.55)
    mw.fill_color = (0.97, 0.98, 1.0)
    page.add_widget(mw)

    # Signature widget
    page.insert_text(pymupdf.Point(48, 575), "Applicant signature:", fontsize=10, fontname="helv")
    sw = pymupdf.Widget()
    sw.field_name = "applicant_signature"
    sw.field_label = "Applicant signature"
    sw.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
    sw.rect = pymupdf.Rect(190, 550, 390, 590)
    sw.border_color = (0.3, 0.35, 0.45)
    page.add_widget(sw)

    doc.save(pdf_path)
    doc.close()


def _seed_single_pdf(
    session: Session,
    uploads_dir: str,
    title: str,
    pdf_filename: str,
) -> None:
    existing = session.exec(
        select(DocumentTemplate).where(DocumentTemplate.name == title)
    ).first()
    if existing:
        return

    pdf_path = os.path.join(uploads_dir, pdf_filename)
    if not os.path.exists(pdf_path):
        return

    # Analyze with deterministic offline geometry/AcroForm during startup seed (fast & free)
    analysis = analyze_pdf_document(pdf_path, use_vision=False)
    doc = pymupdf.open(pdf_path)
    page_count = len(doc)
    doc.close()

    template = DocumentTemplate(
        name=title,
        pdf_filename=pdf_filename,
        page_count=page_count,
        analysis_method=analysis["analysis_method"],
        analysis_summary_json=json.dumps(analysis["analysis_summary"]),
        scraped_content_json=json.dumps(analysis["scraped_storage"]),
    )
    session.add(template)
    session.commit()
    session.refresh(template)

    for m in analysis["mappings"]:
        row = FieldMapping(
            template_id=template.id,
            type=m["type"],
            field_key=m["field_key"],
            label=m.get("label") or humanize_key(m["field_key"]),
            question_text=m.get("question_text"),
            section=m.get("section"),
            match_value=m.get("match_value"),
            x_pct=max(0.0, min(1.0, float(m["x_pct"]))),
            y_pct=max(0.0, min(1.0, float(m["y_pct"]))),
            width_pct=max(0.0, min(1.0, float(m["width_pct"]))) if m.get("width_pct") is not None else None,
            height_pct=max(0.0, min(1.0, float(m["height_pct"]))) if m.get("height_pct") is not None else None,
            qx_pct=m.get("qx_pct"),
            qy_pct=m.get("qy_pct"),
            qw_pct=m.get("qw_pct"),
            qh_pct=m.get("qh_pct"),
            page_number=int(m.get("page_number") or 1),
            font_size=float(m["font_size"]) if m.get("font_size") is not None else None,
            align=m.get("align") or "left",
            confidence=float(m.get("confidence") or 1.0),
            detection_source=m.get("detection_source") or "geometry",
            acroform_field_name=m.get("acroform_field_name"),
        )
        session.add(row)

    session.commit()


def seed_database(session: Session, uploads_dir: str) -> None:
    """
    Seeds two clean, domain-agnostic sample PDFs (a 2-page flat form and an interactive
    AcroForm sample) plus optional local PDFs if SEED_PDFS_DIR is configured.
    """
    os.makedirs(uploads_dir, exist_ok=True)
    create_sample_assets(os.path.join(uploads_dir, "samples"))

    general_filename = "General_Application_Form.pdf"
    _create_general_application_pdf(os.path.join(uploads_dir, general_filename))
    _seed_single_pdf(session, uploads_dir, "General Application & Registration Form", general_filename)

    acro_filename = "Interactive_AcroForm_Sample.pdf"
    _create_interactive_acroform_sample_pdf(os.path.join(uploads_dir, acro_filename))
    _seed_single_pdf(session, uploads_dir, "Interactive Onboarding & Consent Form (AcroForm)", acro_filename)

    # Optional portable directory seeding via SEED_PDFS_DIR environment variable
    seed_dir = os.getenv("SEED_PDFS_DIR", "").strip()
    if seed_dir and os.path.isdir(seed_dir):
        for fname in sorted(os.listdir(seed_dir)):
            if not fname.lower().endswith(".pdf"):
                continue
            src = os.path.join(seed_dir, fname)
            safe_dst_name = re.sub(r"[^a-zA-Z0-9._\-]", "_", fname)
            dst = os.path.join(uploads_dir, safe_dst_name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            title = re.sub(r"[_\-]+", " ", os.path.splitext(fname)[0]).strip()
            _seed_single_pdf(session, uploads_dir, title, safe_dst_name)

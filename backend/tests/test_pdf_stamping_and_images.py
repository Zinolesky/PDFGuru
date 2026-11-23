import io
import os
import tempfile

import pymupdf
from PIL import Image, ImageDraw

from models import FieldMapping
from pdf_service import process_photo_image, process_signature_transparency, stamp_pdf


def _make_ink_image(width: int = 320, height: int = 120) -> bytes:
    img = Image.new("RGB", (width, height), color=(242, 240, 234))
    draw = ImageDraw.Draw(img)
    # Draw asymmetric horizontal stroke so 90-degree rotation clearly changes aspect ratio
    draw.line([(20, 60), (300, 60)], fill=(12, 24, 90), width=6)
    draw.line([(240, 30), (300, 60)], fill=(12, 24, 90), width=5)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vectorized_signature_transparency_and_rotation():
    raw = _make_ink_image(320, 120)
    out_0 = process_signature_transparency(raw, threshold=205, rotate_deg=0)
    out_90 = process_signature_transparency(raw, threshold=205, rotate_deg=90)

    im0 = Image.open(io.BytesIO(out_0))
    im90 = Image.open(io.BytesIO(out_90))
    assert im0.mode == "RGBA"
    # Unrotated stroke is wider than tall; rotated 90 deg is taller than wide
    assert im0.width > im0.height
    assert im90.height > im90.width
    # Background pixels must be transparent (alpha == 0)
    assert im0.getpixel((0, 0))[3] == 0


def test_photo_smart_crop_ratio():
    wide_img = Image.new("RGB", (800, 400), color=(120, 150, 190))
    buf = io.BytesIO()
    wide_img.save(buf, format="PNG")

    cropped = process_photo_image(buf.getvalue(), rotate_deg=0, smart_crop=True)
    im = Image.open(io.BytesIO(cropped))
    assert (im.width, im.height) == (420, 540)


def test_stamp_pdf_unicode_autofit_and_custom_image_slots():
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(pdf_path)
    doc.close()

    try:
        mappings = [
            FieldMapping(
                template_id=1,
                type="text",
                field_key="currency_amount",
                x_pct=0.10,
                y_pct=0.10,
                width_pct=0.35,
                height_pct=0.028,
                page_number=1,
                font_size=11.0,
            ),
            FieldMapping(
                template_id=1,
                type="text",
                field_key="unicode_name",
                x_pct=0.10,
                y_pct=0.16,
                width_pct=0.35,
                height_pct=0.028,
                page_number=1,
                font_size=11.0,
            ),
            # Very tight multiline box with long text to verify ZERO silent dropping
            FieldMapping(
                template_id=1,
                type="multiline",
                field_key="long_notes",
                x_pct=0.10,
                y_pct=0.22,
                width_pct=0.30,
                height_pct=0.055,
                page_number=1,
                font_size=12.0,
            ),
            FieldMapping(
                template_id=1,
                type="checkbox",
                field_key="agreed",
                match_value="Yes",
                x_pct=0.12,
                y_pct=0.34,
                page_number=1,
            ),
            # Arbitrary custom image slot + witness signature with 90° rotation
            FieldMapping(
                template_id=1,
                type="image",
                field_key="company_stamp",
                x_pct=0.10,
                y_pct=0.45,
                width_pct=0.22,
                height_pct=0.08,
                page_number=1,
            ),
            FieldMapping(
                template_id=1,
                type="image",
                field_key="witness_signature",
                x_pct=0.50,
                y_pct=0.45,
                width_pct=0.22,
                height_pct=0.08,
                page_number=1,
            ),
        ]

        sig_bytes = _make_ink_image()
        stamped = stamp_pdf(
            pdf_path=pdf_path,
            mappings=mappings,
            form_data={
                "currency_amount": "₦5,000,000 / €1,250",
                "unicode_name": "Élodie Müller-Peña",
                "long_notes": (
                    "This is a deliberately very long paragraph of explanation meant to verify "
                    "that the iterative auto-shrink textbox fitter never drops text silently."
                ),
                "agreed": "Yes",
            },
            image_slots={
                "company_stamp": {
                    "bytes": sig_bytes,
                    "mode": "signature",
                    "rotate_deg": 0,
                    "threshold": 205,
                },
            },
            witness_signature_bytes=sig_bytes,
            witness_signature_rotate=90,
        )

        out_doc = pymupdf.open(stream=stamped, filetype="pdf")
        text = out_doc[0].get_text("text")
        images = out_doc[0].get_images()
        out_doc.close()

        assert "₦5,000,000" in text
        assert "€1,250" in text
        assert "Élodie" in text
        assert "deliberately very long paragraph" in text
        # Both custom company_stamp AND witness_signature must be embedded
        assert len(images) == 2
    finally:
        os.remove(pdf_path)


def test_open_checkmark_path_and_proportional_paren_sizing():
    """
    Verifies stamped checkmarks are open polylines (`closePath=False`, never filled/closed triangles)
    and scale proportionally inside narrow `(  )` slots vs larger vector squares.
    """
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(pdf_path)
    doc.close()

    try:
        mappings = [
            FieldMapping(
                template_id=1,
                type="checkbox",
                field_key="tight_paren",
                match_value="Yes",
                x_pct=0.50,
                y_pct=0.30,
                width_pct=0.0085,  # ~5.2pt narrow paren gap
                height_pct=0.011,  # ~8.7pt tall
                page_number=1,
            ),
            FieldMapping(
                template_id=1,
                type="checkbox",
                field_key="wide_box",
                match_value="Yes",
                x_pct=0.50,
                y_pct=0.50,
                width_pct=0.024,  # ~14.7pt square box
                height_pct=0.019,  # ~15.0pt tall
                page_number=1,
            ),
        ]

        stamped = stamp_pdf(
            pdf_path=pdf_path,
            mappings=mappings,
            form_data={"tight_paren": "Yes", "wide_box": "Yes"},
        )
        out_doc = pymupdf.open(stream=stamped, filetype="pdf")
        drawings = out_doc[0].get_drawings()
        out_doc.close()

        assert len(drawings) == 2
        drawings.sort(key=lambda d: d["rect"].y0)
        tight_d, wide_d = drawings[0], drawings[1]

        # Open checkmark: only 2 line segments ('l'), never a closed 3-line triangle or filled shape
        assert tight_d.get("closePath") is False
        assert wide_d.get("closePath") is False
        assert tight_d.get("fill") is None
        assert len(tight_d["items"]) == 2
        assert len(wide_d["items"]) == 2

        # Narrow paren checkmark stays compact enough to avoid hitting adjacent '(' / ')' glyphs
        assert tight_d["rect"].width < wide_d["rect"].width
        assert tight_d["rect"].width <= 6.0
        assert wide_d["rect"].width >= 7.0
    finally:
        os.remove(pdf_path)

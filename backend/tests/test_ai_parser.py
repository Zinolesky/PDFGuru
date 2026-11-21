import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from ai_service import parse_input_text


def test_universal_dictionary_parsing_and_multiline():
    expected = [
        {"field_key": "patient_name", "label": "Patient name", "type": "text"},
        {"field_key": "insurance_provider", "label": "Insurance provider", "type": "text"},
        {
            "field_key": "visit_type",
            "label": "Visit type",
            "type": "checkbox",
            "options": ["Routine Checkup", "Urgent Care", "Follow-Up"],
        },
        {"field_key": "symptoms", "label": "Symptoms", "type": "multiline"},
    ]
    raw = (
        "Patient name: Elena Rostova\n"
        "Insurance provider: BlueShield Global\n"
        "Visit type (Routine Checkup / Urgent Care / Follow-Up): follow up\n"
        "Symptoms: Mild headache for two days\n"
        "and slight fatigue in the afternoon.\n"
    )
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        res = parse_input_text(raw, expected_fields=expected)

    assert res.parser_used == "dictionary-heuristic"
    assert res.warning is None
    assert res.fields["patient_name"] == "Elena Rostova"
    assert res.fields["insurance_provider"] == "BlueShield Global"
    # Fuzzy checkbox normalization matches exact option string
    assert res.fields["visit_type"] == "Follow-Up"
    assert "Mild headache" in res.fields["symptoms"]
    assert "slight fatigue" in res.fields["symptoms"]


def test_no_false_positive_domain_leakage():
    """Ensures arbitrary words in text never fabricate unrequested fields or auto-fill today's date."""
    expected = [
        {"field_key": "residential_address", "label": "Residential address", "type": "text"},
        {"field_key": "notes", "label": "Notes", "type": "multiline"},
        {
            "field_key": "marital_status",
            "label": "Marital status",
            "type": "checkbox",
            "options": ["Single", "Married"],
        },
        {"field_key": "date_signed", "label": "Date", "type": "text"},
    ]
    raw = (
        "Residential address: 14 Single Tree Road, Ikeja\n"
        "Notes: Please attach passport photo to the file.\n"
        "Marital status: (Single / Married)\n"
        "Date: \n"
    )
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        res = parse_input_text(raw, expected_fields=expected)

    assert res.fields["residential_address"] == "14 Single Tree Road, Ikeja"
    # Placeholder hint must NOT be parsed, and "Single" inside address must NOT set marital_status!
    assert "marital_status" not in res.fields
    assert "date_signed" not in res.fields
    assert "id_type" not in res.fields
    assert "document_pickup" not in res.fields


def test_mocked_gemini_interactions_api_enforces_checkbox_enums():
    expected = [
        {"field_key": "full_name", "label": "Full name", "type": "text"},
        {
            "field_key": "employment_type",
            "label": "Employment type",
            "type": "checkbox",
            "options": ["Full-Time", "Part-Time", "Contractor"],
        },
    ]

    captured_kwargs = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "full_name": "Marcus Vance",
                        "employment_type": "Contractor",
                    }
                )
            )

    class FakeClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = FakeInteractions()

    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": ""}),
        patch("ai_service.genai.Client", FakeClient),
    ):
        res = parse_input_text(
            "Hi! My name is Marcus Vance and I will be joining as a contractor.",
            expected_fields=expected,
        )

    assert res.parser_used == "gemini-3.5-flash-lite"
    assert captured_kwargs["model"] == "gemini-3.5-flash-lite"
    assert captured_kwargs["generation_config"]["thinking_level"] == "minimal"
    assert res.warning is None
    assert res.fields["full_name"] == "Marcus Vance"
    assert res.fields["employment_type"] == "Contractor"

    # Verify strict dynamic schema included checkbox enum & store=False
    schema = captured_kwargs["response_format"]["schema"]
    assert captured_kwargs["store"] is False
    assert schema["properties"]["employment_type"]["anyOf"][0]["enum"] == [
        "Full-Time",
        "Part-Time",
        "Contractor",
    ]


def test_gemini_error_surfaces_transparent_warning():
    class FailingInteractions:
        def create(self, **kwargs):
            raise RuntimeError("Simulated quota error")

    class FailingClient:
        def __init__(self, api_key=None, http_options=None):
            self.interactions = FailingInteractions()

    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}),
        patch("ai_service.genai.Client", FailingClient),
    ):
        res = parse_input_text("First name: Sam\nLast name: Lee")

    assert res.parser_used == "dictionary-heuristic"
    assert res.warning is not None and "Simulated quota error" in res.warning
    assert res.fields["first_name"] == "Sam"
    assert res.fields["last_name"] == "Lee"

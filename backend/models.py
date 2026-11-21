from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict
from sqlmodel import Field, Relationship, SQLModel


class UniversalFormData(BaseModel):
    """
    Universal, domain-agnostic form data container.
    Accepts any arbitrary field_key -> value mapping discovered on any uploaded PDF.
    """

    model_config = ConfigDict(extra="allow")


class FieldMappingBase(SQLModel):
    type: str = Field(
        description="Mapping type: text, multiline, checkbox, or image"
    )
    field_key: str = Field(
        description="Normalized machine key, e.g. first_name, date_of_birth, applicant_signature"
    )
    label: Optional[str] = Field(
        default=None,
        description="Concise human-readable label for the copyable dictionary format",
    )
    question_text: Optional[str] = Field(
        default=None,
        description="Verbatim question or prompt scraped from the PDF",
    )
    section: Optional[str] = Field(
        default=None,
        description="Section heading under which this input appears",
    )
    match_value: Optional[str] = Field(
        default=None,
        description="Option value that triggers this checkbox/radio mark",
    )
    x_pct: float = Field(description="Normalized answer box X coordinate (0.0 to 1.0)")
    y_pct: float = Field(description="Normalized answer box Y coordinate (0.0 to 1.0)")
    width_pct: Optional[float] = Field(
        default=None, description="Normalized answer box width (0.0 to 1.0)"
    )
    height_pct: Optional[float] = Field(
        default=None, description="Normalized answer box height (0.0 to 1.0)"
    )
    qx_pct: Optional[float] = Field(
        default=None, description="Normalized question/prompt X coordinate (0.0 to 1.0)"
    )
    qy_pct: Optional[float] = Field(
        default=None, description="Normalized question/prompt Y coordinate (0.0 to 1.0)"
    )
    qw_pct: Optional[float] = Field(
        default=None, description="Normalized question/prompt width (0.0 to 1.0)"
    )
    qh_pct: Optional[float] = Field(
        default=None, description="Normalized question/prompt height (0.0 to 1.0)"
    )
    page_number: int = Field(default=1, description="1-indexed PDF page number")
    font_size: Optional[float] = Field(
        default=10.0,
        description="Font size in points (normalized to A4 595pt page width)",
    )
    align: Optional[str] = Field(
        default="left", description="Text alignment: left, center, or right"
    )
    confidence: Optional[float] = Field(
        default=1.0, description="Detection confidence score (0.0 to 1.0)"
    )
    detection_source: Optional[str] = Field(
        default="manual",
        description="Source: acroform, vision_snapped, vision, geometry, or manual",
    )
    acroform_field_name: Optional[str] = Field(
        default=None,
        description="Original native PDF AcroForm widget name if present",
    )


class FieldMapping(FieldMappingBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    template_id: int = Field(foreign_key="documenttemplate.id", index=True)
    template: Optional["DocumentTemplate"] = Relationship(back_populates="mappings")


class DocumentTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    pdf_filename: str
    page_count: int = Field(default=1)
    analysis_method: Optional[str] = Field(default="geometry")
    analysis_summary_json: Optional[str] = Field(default=None)
    scraped_content_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mappings: List[FieldMapping] = Relationship(
        back_populates="template",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class SavedProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    data_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FieldMappingCreate(FieldMappingBase):
    pass


class FieldMappingRead(FieldMappingBase):
    id: int
    template_id: int


class DocumentTemplateRead(SQLModel):
    id: int
    name: str
    pdf_filename: str
    page_count: int
    analysis_method: Optional[str] = None
    analysis_summary: Optional[Dict[str, Any]] = None
    created_at: datetime
    mappings: List[FieldMappingRead] = []


class DetectedFieldSummary(BaseModel):
    field_key: str
    label: str
    question_text: Optional[str] = None
    section: Optional[str] = None
    type: str  # "text" | "multiline" | "checkbox" | "image"
    options: List[str] = []
    page_numbers: List[int] = []
    confidence: Optional[float] = None
    detection_source: Optional[str] = None


class DictionaryFormatResponse(BaseModel):
    template_id: int
    document_name: str
    page_count: int
    analysis_method: Optional[str] = None
    total_mappings: int
    fields: List[DetectedFieldSummary]
    blank_dictionary_text: str
    guided_dictionary_text: str


class ScrapedContentResponse(BaseModel):
    template_id: int
    document_name: str
    page_count: int
    analysis_method: Optional[str] = None
    analysis_summary: Optional[Dict[str, Any]] = None
    pages: List[Dict[str, Any]] = []


class ParseTextRequest(BaseModel):
    raw_text: str
    template_id: Optional[int] = None
    expected_fields: Optional[List[Dict[str, Any]]] = None


class ParseTextResponse(BaseModel):
    fields: Dict[str, Any]
    parser_used: str
    warning: Optional[str] = None


class ProfileCreate(BaseModel):
    name: str
    data: Dict[str, Any]


class ProfileRead(BaseModel):
    id: int
    name: str
    data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

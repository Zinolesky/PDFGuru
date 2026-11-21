# PDFGuru — Universal PDF Scraper & Form Filler (PWA)

**PDFGuru** — Upload any PDF to scrape structured data (tables, sections, key-values), auto-detect fillable fields with Gemini Vision + vector geometry, and stamp clean PDFs.

---

## 1. Architecture & 4-Stage Universal Q→A Detection

1. **Stage 1 — Full Document & Vector Geometry Scrape (`backend/pdf_scraper.py`)**
   - Uses PyMuPDF (`pymupdf`) to extract every page's reading-order text lines, font sizes/bold section headings, native AcroForm widgets, and raw vector drawings (`page.get_drawings()`): horizontal underlines, rectangular input boxes, table grids/cells, small checkbox/radio shapes, and large photo/stamp frames.
   - Classifies every page (`acroform`, `digital_flat`, `scanned_image`, `prose`) and automatically hooks into local Tesseract OCR (`page.get_textpage_ocr`) if installed on the host for offline scanned pages.
2. **Stage 2 — Native AcroForm Direct Extraction (`backend/pdf_analyzer.py`)**
   - Extracts exact widget coordinates for text, multiline boxes, checkboxes, radio button groups, dropdowns, and signatures.
   - Automatically resolves cryptic widget names (`Text1`, `f1_01[0]`) to the nearest adjacent printed question/label.
3. **Stage 3 — Gemini Multimodal Vision + Geometry Snapping (`backend/vision_analyzer.py`)**
   - When `GEMINI_API_KEY` is configured, renders fillable/scanned pages and invokes `gemini-3.5-flash-lite` (configurable via `GEMINI_VISION_MODEL` / `GEMINI_MODEL`) through the official `google-genai >= 3.2.0` **Interactions API** (`client.interactions.create`) with strict JSON Schema `response_format` and `store=False`.
   - Distinguishes headings/legal prose from real questions, returns both `question_box` and `answer_box`, and snaps predicted boxes onto exact Stage 1 vector underlines, cells, and checkbox squares for pixel-sharp alignment.
4. **Stage 4 — Upgraded Offline Vector-Geometry Engine (`backend/pdf_analyzer.py`)**
   - Works completely offline (no API key required) on digital flat PDFs: detects left-labeled underlines, labels above/below/inside boxes, 2-column & multi-row tables, inline fill-in-the-blank sentences (`"I, ________, residing at ________"`), left/right vector checkboxes, and photo/signature/stamp regions.

---

## 2. Project Structure

```text
PDFGuru/
├── backend/
│   ├── assets/fonts/DejaVuSans.ttf  # Embedded Unicode font (₦, €, £, ¥, accents)
│   ├── main.py                      # FastAPI server, uploads, scraping, profiles & PDF stamping
│   ├── models.py                    # Universal SQLModel tables & Pydantic schemas
│   ├── pdf_scraper.py               # Stage 1: Full text, AcroForm & vector geometry scraper
│   ├── vision_analyzer.py           # Stage 3: Gemini Interactions API Vision + geometry snap
│   ├── pdf_analyzer.py              # 4-stage Q->A orchestrator + dictionary format generator
│   ├── ai_service.py                # Dynamic-schema Gemini & deterministic Key:Value parser
│   ├── pdf_service.py               # Zero-drop auto-fit Unicode stamper + NumPy signature processor
│   ├── seed.py                      # Seeds universal flat & AcroForm demo PDFs + demo media
│   ├── requirements.txt             # UTF-8 Python dependencies
│   └── tests/                       # Comprehensive pytest suite
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # PDFGuru PWA shell & mode switcher
│   │   ├── constants.js             # Universal field presets & dictionary helpers
│   │   └── components/
│   │       ├── FormFiller.jsx           # Orchestrator with auto-saved drafts
│   │       ├── DocumentPickerCard.jsx   # Upload, select, delete & re-scan documents
│   │       ├── ScrapedDataView.jsx      # First-class scraped tables, key-values, sections & JSON export
│   │       ├── DictionaryWorkbench.jsx  # Copy/share Key:Value format & AI extraction
│   │       ├── DynamicFormFields.jsx    # Section-grouped text, multiline & checkbox inputs
│   │       ├── MediaStudio.jsx          # Dynamic slots for any photo/signature/stamp + debounce
│   │       ├── PdfPreviewPane.jsx       # Multi-page preview, download & Web Share
│   │       ├── SavedProfilesDrawer.jsx  # Save & reuse filled data profiles across any PDF
│   │       ├── TemplateBuilder.jsx      # Touch/mouse Q->A visual mapper (move/resize/undo/zoom)
│   │       └── PdfPageCanvas.jsx        # PDF.js canvas with server PNG fallback & zoom
│   └── vite.config.js               # Single-source-of-truth VitePWA + API proxy
├── docker-compose.yml
└── README.md
```

---

## 3. Running Locally

### Backend (`/backend`)
```powershell
cd backend
.\.venv\Scripts\uvicorn main:app --host 127.0.0.1 --port 8005 --reload
```
- Optional: Copy `backend/.env.example` to `backend/.env` and add `GEMINI_API_KEY` to enable Gemini Vision Q→A detection (including scanned/image-only PDFs) and AI unstructured-text extraction.
- Without a key, PDFGuru runs completely offline using AcroForm extraction, vector geometry Q→A detection, and deterministic dictionary parsing.
- Health check: `http://127.0.0.1:8005/api/health` | Swagger UI: `http://127.0.0.1:8005/docs`.

### Frontend (`/frontend`)
```powershell
cd frontend
npm install
npm run dev
```
- By default, `vite.config.js` proxies `/api` to `http://127.0.0.1:8005` (override with `VITE_API_TARGET`).
- Open the local URL printed by Vite (e.g., `http://localhost:5173`).

### Running with Docker
```bash
docker compose up --build
```
- Serves the PWA on `http://localhost:5173` and the backend API on `http://localhost:8000`.

---

## 4. Verification & Tests

```powershell
# Backend lint & test suite
cd backend
.\.venv\Scripts\ruff check .
.\.venv\Scripts\pytest -v

# Frontend production build
cd ..\frontend
npm run build
```

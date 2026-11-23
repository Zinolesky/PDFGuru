import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  FileUp,
  Plus,
  Smartphone,
  Upload,
  CheckCircle2,
  X,
} from 'lucide-react';
import FormFiller from './components/FormFiller';
import TemplateBuilder from './components/TemplateBuilder';

export default function App() {
  const [activeTab, setActiveTab] = useState('filler'); // 'filler' | 'builder'
  const [templates, setTemplates] = useState([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [isDraggingPdf, setIsDraggingPdf] = useState(false);
  const [appNotice, setAppNotice] = useState(null);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const dragCounterRef = useRef(0);

  const activeTemplate =
    templates.find((t) => t.id === Number(selectedTemplateId)) || templates[0] || null;

  const fetchTemplates = useCallback(async (preferredId = null) => {
    try {
      const res = await fetch('/api/templates');
      if (!res.ok) return;
      const data = await res.json();
      setTemplates(data);
      if (preferredId && data.some((t) => t.id === preferredId)) {
        setSelectedTemplateId(preferredId);
      } else {
        setSelectedTemplateId((prev) => {
          if (prev && data.some((t) => t.id === prev)) return prev;
          return data.length > 0 ? data[0].id : null;
        });
      }
    } catch (err) {
      console.error('Failed to fetch templates:', err);
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  useEffect(() => {
    fetchTemplates();

    const handleBeforeInstallPrompt = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
  }, [fetchTemplates]);

  useEffect(() => {
    if (!appNotice || appNotice.type === 'error') return undefined;
    const t = setTimeout(() => setAppNotice(null), 5000);
    return () => clearTimeout(t);
  }, [appNotice]);

  const handleUploadPdf = useCallback(
    async (file) => {
      if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
        setAppNotice({
          type: 'error',
          text: 'Please choose a valid .pdf document.',
        });
        return;
      }
      setUploadingPdf(true);
      setAppNotice(null);
      try {
        const uploadOnce = async (useVisionFlag) => {
          const fd = new FormData();
          fd.append('auto_analyze', 'true');
          fd.append('use_vision', useVisionFlag ? 'true' : 'false');
          fd.append('pdf_file', file);
          return fetch('/api/templates', {
            method: 'POST',
            body: fd,
          });
        };

        let res = await uploadOnce(true);
        // If Vercel Serverless hits a 504 timeout on a large multi-page Vision scan, automatically retry with fast offline geometry/AcroForm
        if (res.status === 504 || res.status === 502) {
          res = await uploadOnce(false);
        }

        if (!res.ok) {
          let detail =
            res.status === 413
              ? 'PDF exceeds Vercel Serverless 4.5 MB upload limit. Please compress or split the PDF.'
              : `Failed to upload PDF (HTTP ${res.status})`;
          try {
            const err = await res.json();
            detail = err.detail || detail;
          } catch {
            // ignore JSON parse errors
          }
          throw new Error(detail);
        }
        const created = await res.json();
        await fetchTemplates(created.id);
        setSelectedTemplateId(created.id);
        setAppNotice({
          type: 'success',
          text: `Opened "${created.name}" (${created.mappings?.length || 0} fields detected).`,
        });
      } catch (err) {
        setAppNotice({ type: 'error', text: err.message });
      } finally {
        setUploadingPdf(false);
      }
    },
    [fetchTemplates]
  );

  const handleDeleteTemplate = useCallback(
    async (templateId) => {
      try {
        const res = await fetch(`/api/templates/${templateId}`, { method: 'DELETE' });
        if (res.ok) {
          await fetchTemplates();
          setAppNotice({ type: 'success', text: 'Document deleted.' });
        }
      } catch (err) {
        setAppNotice({ type: 'error', text: `Failed to delete document: ${err.message}` });
      }
    },
    [fetchTemplates]
  );

  // Global drag-and-drop PDF anywhere on window (without hijacking image drops)
  useEffect(() => {
    const isImageDrag = (e) => {
      if (e.target?.closest?.('[data-image-dropzone="true"]')) return true;
      const items = Array.from(e.dataTransfer?.items || []);
      return items.some((it) => it.kind === 'file' && it.type.startsWith('image/'));
    };

    const hasFileDrag = (e) =>
      Array.from(e.dataTransfer?.types || []).includes('Files');

    const onDragEnter = (e) => {
      if (!hasFileDrag(e) || isImageDrag(e)) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      setIsDraggingPdf(true);
    };

    const onDragOver = (e) => {
      if (!hasFileDrag(e) || isImageDrag(e)) return;
      e.preventDefault();
    };

    const onDragLeave = (e) => {
      if (!hasFileDrag(e)) return;
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) {
        setIsDraggingPdf(false);
      }
    };

    const onDrop = (e) => {
      dragCounterRef.current = 0;
      setIsDraggingPdf(false);
      if (e.target?.closest?.('[data-image-dropzone="true"]')) return;
      const file = e.dataTransfer?.files?.[0];
      if (!file) return;
      if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
        e.preventDefault();
        handleUploadPdf(file);
      }
    };

    window.addEventListener('dragenter', onDragEnter);
    window.addEventListener('dragover', onDragOver);
    window.addEventListener('dragleave', onDragLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onDragEnter);
      window.removeEventListener('dragover', onDragOver);
      window.removeEventListener('dragleave', onDragLeave);
      window.removeEventListener('drop', onDrop);
    };
  }, [handleUploadPdf]);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    setDeferredPrompt(null);
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      {/* Slim Single-Row Header */}
      <header className="sticky top-0 z-40 bg-slate-900 text-white border-b border-slate-800 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
          {/* Left: Brand + Document Switcher */}
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-amber-400 text-slate-950 flex items-center justify-center font-black text-sm shrink-0">
              PG
            </div>
            <span className="text-sm font-extrabold tracking-tight text-white shrink-0">
              PDFGuru
            </span>

            {templates.length > 0 && (
              <select
                data-testid="document-template-select"
                aria-label="Select document"
                value={activeTemplate?.id || ''}
                onChange={(e) => setSelectedTemplateId(Number(e.target.value))}
                className="max-w-[200px] sm:max-w-[260px] truncate rounded-full border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer"
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Center: 2-Tab Segmented Switcher */}
          <div className="inline-flex rounded-xl bg-slate-800 p-1 border border-slate-700">
            <button
              type="button"
              data-testid="nav-filler-tab"
              onClick={() => setActiveTab('filler')}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
                activeTab === 'filler'
                  ? 'bg-amber-400 text-slate-950 shadow-xs'
                  : 'text-slate-300 hover:text-white'
              }`}
            >
              Fill
            </button>
            <button
              type="button"
              data-testid="nav-builder-tab"
              onClick={() => setActiveTab('builder')}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
                activeTab === 'builder'
                  ? 'bg-amber-400 text-slate-950 shadow-xs'
                  : 'text-slate-300 hover:text-white'
              }`}
            >
              Adjust Boxes
            </button>
          </div>

          {/* Right: Single Primary Upload PDF + Optional Install */}
          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5 rounded-xl bg-amber-400 hover:bg-amber-300 text-slate-950 font-bold text-xs px-3.5 py-2 shadow-xs transition cursor-pointer">
              <Plus className="w-3.5 h-3.5" />
              <span>{uploadingPdf ? 'Uploading...' : 'Upload PDF'}</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={uploadingPdf}
                data-testid="quick-upload-pdf-input"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUploadPdf(file);
                  e.target.value = '';
                }}
                className="hidden"
              />
            </label>

            {deferredPrompt && (
              <button
                type="button"
                onClick={handleInstallClick}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition cursor-pointer"
              >
                <Smartphone className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Install App</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-5">
        {uploadingPdf && (
          <div
            data-testid="uploading-banner"
            className="mb-4 rounded-xl px-4 py-3 text-xs font-semibold flex items-center gap-3 bg-slate-900 text-white shadow-sm"
          >
            <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin shrink-0" />
            <span>Scraping PDF content &amp; detecting fillable fields...</span>
          </div>
        )}

        {appNotice && (
          <div
            className={`mb-4 rounded-xl px-4 py-2.5 text-xs font-medium flex items-center justify-between border ${
              appNotice.type === 'error'
                ? 'bg-red-50 border-red-200 text-red-800'
                : 'bg-emerald-50 border-emerald-200 text-emerald-900'
            }`}
          >
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{appNotice.text}</span>
            </div>
            <button
              type="button"
              onClick={() => setAppNotice(null)}
              className="p-0.5 opacity-70 hover:opacity-100 cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {!loadingTemplates && templates.length === 0 ? (
          <div className="max-w-lg mx-auto mt-16 bg-white rounded-3xl border-2 border-dashed border-slate-300 p-10 text-center space-y-4 shadow-sm">
            <div className="w-14 h-14 rounded-2xl bg-amber-100 text-amber-700 flex items-center justify-center mx-auto">
              <FileUp className="w-7 h-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-lg font-bold text-slate-900">Drop any PDF here to get started</h2>
              <p className="text-sm text-slate-500">
                Upload any form, application, or contract and we&apos;ll detect the fillable fields automatically.
              </p>
            </div>
            <label className="inline-flex items-center gap-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm px-5 py-3 shadow-sm transition cursor-pointer">
              <Upload className="w-4 h-4 text-amber-400" />
              {uploadingPdf ? 'Scanning PDF...' : 'Choose PDF File'}
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={uploadingPdf}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUploadPdf(file);
                  e.target.value = '';
                }}
                className="hidden"
              />
            </label>
          </div>
        ) : activeTab === 'filler' ? (
          <FormFiller
            activeTemplate={activeTemplate}
            onTemplatesRefresh={fetchTemplates}
            onDeleteTemplate={handleDeleteTemplate}
            onOpenMapper={() => setActiveTab('builder')}
          />
        ) : (
          <TemplateBuilder
            activeTemplate={activeTemplate}
            onTemplatesRefresh={fetchTemplates}
          />
        )}
      </main>

      {/* Global PDF Drag-and-Drop Overlay */}
      {isDraggingPdf && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-6 pointer-events-none">
          <div className="bg-white rounded-3xl border-2 border-dashed border-amber-500 px-10 py-8 text-center shadow-2xl space-y-2">
            <FileUp className="w-10 h-10 text-amber-600 mx-auto" />
            <p className="text-base font-bold text-slate-900">Drop PDF to open</p>
            <p className="text-xs text-slate-500">We&apos;ll scan all fields automatically</p>
          </div>
        </div>
      )}
    </div>
  );
}

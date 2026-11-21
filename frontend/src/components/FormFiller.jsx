import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  CheckCircle2,
  FileCheck2,
  X,
} from 'lucide-react';
import DocumentPickerCard from './DocumentPickerCard';
import DictionaryWorkbench from './DictionaryWorkbench';
import DynamicFormFields from './DynamicFormFields';
import MediaStudio from './MediaStudio';
import PdfPreviewPane from './PdfPreviewPane';
import SavedProfilesDrawer from './SavedProfilesDrawer';
import ScrapedDataView from './ScrapedDataView';
import {
  SAMPLE_DEMO_VALUES,
  buildDocumentDictionarySpec,
  isSignatureLikeKey,
} from '../constants';

const DRAFT_PREFIX = 'pdfguru_draft_v3_';

export default function FormFiller({
  activeTemplate,
  onTemplatesRefresh,
  onDeleteTemplate,
  onOpenMapper,
}) {
  const localFallbackSpec = useMemo(
    () => buildDocumentDictionarySpec(activeTemplate),
    [activeTemplate]
  );
  const [serverSpec, setServerSpec] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!activeTemplate?.id) {
      setServerSpec(null);
      return undefined;
    }
    (async () => {
      try {
        const res = await fetch(`/api/templates/${activeTemplate.id}/dictionary-format`);
        if (res.ok && !cancelled) {
          const data = await res.json();
          const nonImageFields = (data.fields || []).filter((f) => f.type !== 'image');
          const imageFields = (data.fields || []).filter((f) => f.type === 'image');
          setServerSpec({
            fields: data.fields || [],
            nonImageFields,
            imageFields,
            blankDictionaryText: data.blank_dictionary_text || '',
            guidedDictionaryText: data.guided_dictionary_text || '',
          });
        }
      } catch {
        if (!cancelled) setServerSpec(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTemplate?.id, activeTemplate?.mappings?.length]);

  const docSpec = serverSpec || localFallbackSpec;

  // Sub-tab inside left column: 'fill' | 'scraped' | 'text'
  const [leftTab, setLeftTab] = useState('fill');

  // Dictionary & form state
  const [includeOptionHints, setIncludeOptionHints] = useState(false);
  const [dictionaryText, setDictionaryText] = useState('');
  const [copiedBlank, setCopiedBlank] = useState(false);

  const [formData, setFormData] = useState({});
  const [parsing, setParsing] = useState(false);
  const [parserInfo, setParserInfo] = useState(null);
  const [reanalyzing, setReanalyzing] = useState(false);

  // Dynamic media slots
  const [mediaSlots, setMediaSlots] = useState({});
  const [pasteTarget, setPasteTarget] = useState('profile_photo');
  const [profilesOpen, setProfilesOpen] = useState(false);

  // Stamped PDF output & preview state
  const [generatingPdf, setGeneratingPdf] = useState(false);
  const [generatedPdfBlob, setGeneratedPdfBlob] = useState(null);
  const [generatedPdfUrl, setGeneratedPdfUrl] = useState(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [statusMessage, setStatusMessage] = useState(null);

  const mappedPages = useMemo(() => {
    if (!activeTemplate?.mappings?.length) return [1];
    const pages = Array.from(
      new Set(activeTemplate.mappings.map((m) => m.page_number || 1))
    ).sort((a, b) => a - b);
    return pages.length ? pages : [1];
  }, [activeTemplate]);

  const totalTemplatePages = activeTemplate?.page_count || 1;

  // Auto-dismiss info/success toast after 5 seconds
  useEffect(() => {
    if (!statusMessage || statusMessage.type === 'error') return undefined;
    const t = setTimeout(() => setStatusMessage(null), 5000);
    return () => clearTimeout(t);
  }, [statusMessage]);

  // Restore saved localStorage draft whenever active template changes
  useEffect(() => {
    if (!activeTemplate?.id) return;
    const draftKey = `${DRAFT_PREFIX}${activeTemplate.id}`;
    let restored = {};
    try {
      const raw = localStorage.getItem(draftKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') {
          restored = parsed;
        }
      }
    } catch {
      restored = {};
    }
    setFormData(restored);
    setPreviewPage(mappedPages[0] || 1);
    setGeneratedPdfUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setGeneratedPdfBlob(null);
    setParserInfo(null);
    setLeftTab((activeTemplate.mappings?.length || 0) === 0 ? 'scraped' : 'fill');
  }, [activeTemplate?.id]);

  // Keep pasteTarget valid for the active document's image slots
  useEffect(() => {
    const imgs = docSpec.imageFields || [];
    if (imgs.length > 0 && !imgs.some((f) => f.field_key === pasteTarget)) {
      setPasteTarget(imgs[0].field_key);
    }
  }, [docSpec.imageFields, pasteTarget]);

  // Sync dictionary textarea when template spec updates
  useEffect(() => {
    if (!activeTemplate) return;
    const baseText = includeOptionHints
      ? docSpec.guidedDictionaryText
      : docSpec.blankDictionaryText;
    setDictionaryText(baseText);
  }, [activeTemplate?.id, docSpec.blankDictionaryText, docSpec.guidedDictionaryText, includeOptionHints]);

  // Auto-save draft per template
  useEffect(() => {
    if (!activeTemplate?.id) return;
    const draftKey = `${DRAFT_PREFIX}${activeTemplate.id}`;
    try {
      const hasAny = Object.values(formData).some(
        (v) => v !== null && v !== undefined && String(v).trim() !== ''
      );
      if (hasAny) {
        localStorage.setItem(draftKey, JSON.stringify(formData));
      } else {
        localStorage.removeItem(draftKey);
      }
    } catch {
      // ignore storage quota errors
    }
  }, [activeTemplate?.id, formData]);

  const handleMediaFileChange = useCallback((slotKey, file) => {
    setMediaSlots((prev) => {
      const existing = prev[slotKey] || {};
      const defaultMode = isSignatureLikeKey(slotKey) ? 'signature' : 'photo';
      return {
        ...prev,
        [slotKey]: {
          mode: existing.mode || defaultMode,
          threshold: existing.threshold ?? 205,
          smartCrop: existing.smartCrop ?? true,
          previewUrl: existing.previewUrl || null,
          rotateDeg: 0,
          file,
        },
      };
    });
  }, []);

  const handleUpdateSlotState = useCallback((slotKey, patch, revokeOldPreview = false) => {
    setMediaSlots((prev) => {
      const existing = prev[slotKey] || {};
      if (revokeOldPreview && existing.previewUrl && existing.previewUrl !== patch.previewUrl) {
        URL.revokeObjectURL(existing.previewUrl);
      }
      return {
        ...prev,
        [slotKey]: { ...existing, ...patch },
      };
    });
  }, []);

  const handleClearSlot = useCallback((slotKey) => {
    setMediaSlots((prev) => {
      const existing = prev[slotKey];
      if (existing?.previewUrl) {
        URL.revokeObjectURL(existing.previewUrl);
      }
      const next = { ...prev };
      delete next[slotKey];
      return next;
    });
  }, []);

  // Global Ctrl+V clipboard image paste into active pasteTarget
  useEffect(() => {
    const handleWindowPaste = (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i += 1) {
        const item = items[i];
        if (item.type && item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          if (!blob) continue;
          e.preventDefault();
          const pastedFile = new File(
            [blob],
            `pasted_${pasteTarget}_${Date.now()}.png`,
            { type: blob.type || 'image/png' }
          );
          handleMediaFileChange(pasteTarget, pastedFile);
          setStatusMessage({
            type: 'info',
            text: `Pasted image into "${pasteTarget}".`,
          });
          break;
        }
      }
    };
    window.addEventListener('paste', handleWindowPaste);
    return () => window.removeEventListener('paste', handleWindowPaste);
  }, [pasteTarget, handleMediaFileChange]);

  const handleLoadDemo = async () => {
    // 1. Populate all fields on the active PDF with realistic sample values
    const nextData = {};
    const sampleLines = (docSpec.nonImageFields || []).map((f) => {
      let demoVal = SAMPLE_DEMO_VALUES[f.field_key];
      if (!demoVal) {
        if (f.type === 'checkbox' && f.options?.length > 0) {
          demoVal = f.options[0];
        } else {
          demoVal = `Sample ${f.label}`;
        }
      }
      nextData[f.field_key] = demoVal;
      const keyLabel =
        includeOptionHints && f.type === 'checkbox' && f.options?.length > 0
          ? `${f.label} (${f.options.join(' / ')})`
          : f.label;
      return `${keyLabel}: ${demoVal}`;
    });
    setFormData((prev) => ({ ...prev, ...nextData }));
    setDictionaryText(sampleLines.join('\n'));

    // 2. Load sample images into any image slots on this PDF
    const imgFields = docSpec.imageFields || [];
    if (imgFields.length > 0) {
      try {
        const [photoRes, sigRes, witRes] = await Promise.all([
          fetch('/api/samples/photo'),
          fetch('/api/samples/signature'),
          fetch('/api/samples/witness_signature'),
        ]);
        const photoBlob = photoRes.ok ? await photoRes.blob() : null;
        const sigBlob = sigRes.ok ? await sigRes.blob() : null;
        const witBlob = witRes.ok ? await witRes.blob() : null;

        imgFields.forEach((slot) => {
          const k = slot.field_key.toLowerCase();
          if (k.includes('witness') && witBlob) {
            handleMediaFileChange(
              slot.field_key,
              new File([witBlob], `${slot.field_key}.png`, { type: 'image/png' })
            );
          } else if (isSignatureLikeKey(k) && sigBlob) {
            handleMediaFileChange(
              slot.field_key,
              new File([sigBlob], `${slot.field_key}.png`, { type: 'image/png' })
            );
          } else if (photoBlob) {
            handleMediaFileChange(
              slot.field_key,
              new File([photoBlob], `${slot.field_key}.png`, { type: 'image/png' })
            );
          }
        });
      } catch {
        // ignore sample image load error
      }
    }

    setLeftTab('fill');
    setStatusMessage({
      type: 'success',
      text: 'Loaded sample answers and demo media!',
    });
  };

  const handleReanalyzeDocument = async () => {
    if (!activeTemplate) return;
    setReanalyzing(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`/api/templates/${activeTemplate.id}/analyze?use_vision=true`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to re-scan PDF fields');
      const updated = await res.json();
      if (onTemplatesRefresh) {
        await onTemplatesRefresh(updated.id);
      }
      setStatusMessage({
        type: 'success',
        text: `Re-scanned "${updated.name}" (${updated.mappings?.length || 0} fields found).`,
      });
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.message });
    } finally {
      setReanalyzing(false);
    }
  };

  const handleToggleOptionHints = (nextVal) => {
    setIncludeOptionHints(nextVal);
    const lines = (docSpec.nonImageFields || []).map((f) => {
      const currentVal = formData[f.field_key] || '';
      const keyLabel =
        nextVal && f.type === 'checkbox' && f.options?.length > 0
          ? `${f.label} (${f.options.join(' / ')})`
          : f.label;
      return `${keyLabel}: ${currentVal}`;
    });
    setDictionaryText(lines.join('\n'));
  };

  const handleCopyBlankFormat = async () => {
    const textToCopy = includeOptionHints
      ? docSpec.guidedDictionaryText
      : docSpec.blankDictionaryText;
    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopiedBlank(true);
      setTimeout(() => setCopiedBlank(false), 2500);
      setStatusMessage({
        type: 'success',
        text: 'Copied blank questions to clipboard!',
      });
    } catch {
      setStatusMessage({
        type: 'error',
        text: 'Clipboard copy failed — please copy the text manually.',
      });
    }
  };

  const handleShareFormat = async () => {
    const formatStr = includeOptionHints
      ? docSpec.guidedDictionaryText
      : docSpec.blankDictionaryText;
    const message = `Please fill in your details for *${
      activeTemplate?.name || 'the document'
    }* by replying with this format:\n\n${formatStr}`;

    if (navigator.share) {
      try {
        await navigator.share({
          title: `${activeTemplate?.name || 'Document'} — Questions`,
          text: message,
        });
        return;
      } catch {
        // fallback below
      }
    }
    try {
      await navigator.clipboard.writeText(message);
      setStatusMessage({
        type: 'success',
        text: 'Share message copied to clipboard — paste it into any app!',
      });
    } catch {
      const mailUrl = `mailto:?subject=${encodeURIComponent(
        `${activeTemplate?.name || 'Document'} Details`
      )}&body=${encodeURIComponent(message)}`;
      window.open(mailUrl, '_blank', 'noopener,noreferrer');
    }
  };

  const handleParseDictionary = async () => {
    if (!dictionaryText.trim()) {
      setStatusMessage({
        type: 'error',
        text: 'Paste filled answers or notes first.',
      });
      return;
    }
    setParsing(true);
    setStatusMessage(null);
    try {
      const res = await fetch('/api/parse-dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_text: dictionaryText,
          template_id: activeTemplate?.id || null,
          expected_fields: docSpec.nonImageFields || [],
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Could not extract values');
      }
      const result = await res.json();
      const extracted = result.fields || {};
      setParserInfo({ parser_used: result.parser_used, warning: result.warning });

      setFormData((prev) => {
        const merged = { ...prev };
        Object.keys(extracted).forEach((k) => {
          if (
            extracted[k] !== undefined &&
            extracted[k] !== null &&
            String(extracted[k]).trim() !== ''
          ) {
            merged[k] = extracted[k];
          }
        });
        return merged;
      });
      setLeftTab('fill');
      setStatusMessage({
        type: 'success',
        text: `Auto-filled ${Object.keys(extracted).length} field(s)!`,
      });
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.message });
    } finally {
      setParsing(false);
    }
  };

  const handleFieldChange = (key, value) => {
    setFormData((prev) => {
      const next = {
        ...prev,
        [key]: value === '' ? null : value,
      };
      if (key === 'last_name') next.surname = value || null;
      else if (key === 'surname') next.last_name = value || null;
      return next;
    });
  };

  const handleClearForm = () => {
    setFormData({});
    Object.keys(mediaSlots).forEach((k) => handleClearSlot(k));
    if (activeTemplate?.id) {
      localStorage.removeItem(`${DRAFT_PREFIX}${activeTemplate.id}`);
    }
    setStatusMessage({ type: 'info', text: 'Cleared form.' });
  };

  const handleApplyProfile = (profile) => {
    const incoming = profile.data || {};
    setFormData((prev) => ({ ...prev, ...incoming }));
    setLeftTab('fill');
    setStatusMessage({
      type: 'success',
      text: `Loaded profile "${profile.name}".`,
    });
  };

  const handleGeneratePdf = async () => {
    if (!activeTemplate) return;
    setGeneratingPdf(true);
    setStatusMessage(null);
    try {
      const multipart = new FormData();
      multipart.append('template_id', String(activeTemplate.id));
      multipart.append('form_data', JSON.stringify(formData));

      const slotsMeta = {};
      Object.entries(mediaSlots).forEach(([slotKey, cfg]) => {
        if (!cfg?.file) return;
        multipart.append(`image_slot__${slotKey}`, cfg.file);
        slotsMeta[slotKey] = {
          mode: cfg.mode || (isSignatureLikeKey(slotKey) ? 'signature' : 'photo'),
          rotate_deg: cfg.rotateDeg || 0,
          threshold: cfg.threshold ?? 205,
          smart_crop: cfg.smartCrop ?? true,
        };
      });
      multipart.append('image_slots_meta', JSON.stringify(slotsMeta));

      const res = await fetch('/api/generate-pdf', {
        method: 'POST',
        body: multipart,
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || 'Failed to create PDF');
      }
      const pdfBlob = await res.blob();
      setGeneratedPdfUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(pdfBlob);
      });
      setGeneratedPdfBlob(pdfBlob);
      if (mappedPages.length > 0 && !mappedPages.includes(previewPage)) {
        setPreviewPage(mappedPages[0]);
      }
      setStatusMessage({
        type: 'success',
        text: 'Your filled PDF is ready! Download or share it from the preview.',
      });
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.message });
    } finally {
      setGeneratingPdf(false);
    }
  };

  const getOutputFilename = () => {
    const personSlug = (
      formData.last_name ||
      formData.surname ||
      formData.first_name ||
      formData.full_name ||
      'Completed'
    )
      .trim()
      .replace(/\s+/g, '_');
    const docSlug = (activeTemplate?.name || 'Document')
      .trim()
      .replace(/[^a-zA-Z0-9]+/g, '_');
    return `PDFGuru_${docSlug}_${personSlug}.pdf`;
  };

  const handleDownloadPdf = () => {
    if (!generatedPdfUrl) return;
    const a = document.createElement('a');
    a.href = generatedPdfUrl;
    a.download = getOutputFilename();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleSharePdf = async () => {
    if (!generatedPdfBlob) return;
    const filename = getOutputFilename();
    const pdfFileObj = new File([generatedPdfBlob], filename, { type: 'application/pdf' });
    const shareTitle = `${activeTemplate?.name || 'Completed'} PDF`;
    const shareText = `Completed PDF: ${activeTemplate?.name || 'Document'}.`;

    if (navigator.canShare && navigator.canShare({ files: [pdfFileObj] })) {
      try {
        await navigator.share({ title: shareTitle, text: shareText, files: [pdfFileObj] });
        return;
      } catch (err) {
        if (err.name === 'AbortError') return;
      }
    }
    handleDownloadPdf();
    setStatusMessage({
      type: 'info',
      text: `Downloaded "${filename}" — attach it directly in your messaging or email app.`,
    });
  };

  // Live X / Y progress counter
  const { filledCount, totalCount, hasAnyValue } = useMemo(() => {
    const nonImg = docSpec.nonImageFields || [];
    const img = docSpec.imageFields || [];
    const filledText = nonImg.filter((f) => {
      const v = formData[f.field_key];
      return v !== null && v !== undefined && String(v).trim() !== '';
    }).length;
    const filledImg = img.filter((f) => Boolean(mediaSlots[f.field_key]?.file)).length;
    const anyExtra =
      Object.values(formData).some(
        (v) => v !== null && v !== undefined && String(v).trim() !== ''
      ) || Object.values(mediaSlots).some((s) => Boolean(s?.file));
    return {
      filledCount: filledText + filledImg,
      totalCount: nonImg.length + img.length,
      hasAnyValue: anyExtra,
    };
  }, [docSpec.nonImageFields, docSpec.imageFields, formData, mediaSlots]);

  return (
    <div className="space-y-4">
      <DocumentPickerCard
        activeTemplate={activeTemplate}
        docSpec={docSpec}
        reanalyzing={reanalyzing}
        onOpenProfiles={() => setProfilesOpen(true)}
        onLoadDemo={handleLoadDemo}
        onReanalyze={handleReanalyzeDocument}
        onViewScraped={() => setLeftTab('scraped')}
        onOpenMapper={onOpenMapper}
        onDeleteTemplate={onDeleteTemplate}
      />

      {statusMessage && (
        <div
          data-testid="status-banner"
          className={`rounded-xl px-4 py-2.5 text-xs font-medium flex items-center justify-between border ${
            statusMessage.type === 'error'
              ? 'bg-red-50 border-red-200 text-red-800'
              : statusMessage.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
              : 'bg-amber-50 border-amber-200 text-amber-900'
          }`}
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{statusMessage.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setStatusMessage(null)}
            className="p-0.5 opacity-70 hover:opacity-100 cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Calm 2-Column Workspace (6 + 6) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT: Tabbed Fill Card + Sticky Footer CTA */}
        <div className="lg:col-span-6 bg-white rounded-2xl border border-slate-200/90 shadow-sm flex flex-col overflow-hidden">
          {/* Sub-Tab Header */}
          <div className="px-4 pt-3 pb-0 border-b border-slate-200 flex items-center justify-between gap-2 bg-slate-50/60 overflow-x-auto">
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setLeftTab('fill')}
                data-testid="tab-fill-form"
                className={`inline-flex items-center gap-2 px-3.5 py-2.5 text-xs font-bold border-b-2 transition cursor-pointer whitespace-nowrap ${
                  leftTab === 'fill'
                    ? 'border-slate-900 text-slate-900 bg-white rounded-t-xl'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <span>Fill Fields</span>
                {totalCount > 0 && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
                    {filledCount} / {totalCount}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setLeftTab('scraped')}
                data-testid="tab-scraped-data"
                className={`px-3.5 py-2.5 text-xs font-bold border-b-2 transition cursor-pointer whitespace-nowrap ${
                  leftTab === 'scraped'
                    ? 'border-slate-900 text-slate-900 bg-white rounded-t-xl'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                Scraped Data
              </button>

              <button
                type="button"
                onClick={() => setLeftTab('text')}
                data-testid="tab-paste-text"
                className={`px-3.5 py-2.5 text-xs font-bold border-b-2 transition cursor-pointer whitespace-nowrap ${
                  leftTab === 'text'
                    ? 'border-slate-900 text-slate-900 bg-white rounded-t-xl'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                Paste / Share Text
              </button>
            </div>
          </div>

          {/* Scrollable Form / Scraped / Text Body */}
          <div className="p-5 space-y-5 lg:max-h-[calc(100vh-16rem)] lg:overflow-y-auto">
            {leftTab === 'fill' ? (
              <>
                <DynamicFormFields
                  docSpec={docSpec}
                  formData={formData}
                  onFieldChange={handleFieldChange}
                  onOpenMapper={onOpenMapper}
                />
                <MediaStudio
                  imageFields={docSpec.imageFields}
                  mediaSlots={mediaSlots}
                  pasteTarget={pasteTarget}
                  onSelectPasteTarget={setPasteTarget}
                  onFileChange={handleMediaFileChange}
                  onUpdateSlotState={handleUpdateSlotState}
                  onClearSlot={handleClearSlot}
                  onOpenMapper={onOpenMapper}
                />
              </>
            ) : leftTab === 'scraped' ? (
              <ScrapedDataView
                activeTemplate={activeTemplate}
                onOpenMapper={onOpenMapper}
              />
            ) : (
              <DictionaryWorkbench
                dictionaryText={dictionaryText}
                includeOptionHints={includeOptionHints}
                copiedBlank={copiedBlank}
                parsing={parsing}
                parserInfo={parserInfo}
                onDictionaryTextChange={setDictionaryText}
                onToggleOptionHints={handleToggleOptionHints}
                onResetBlank={() =>
                  setDictionaryText(
                    includeOptionHints
                      ? docSpec.guidedDictionaryText
                      : docSpec.blankDictionaryText
                  )
                }
                onCopyBlankFormat={handleCopyBlankFormat}
                onShareFormat={handleShareFormat}
                onParseDictionary={handleParseDictionary}
              />
            )}
          </div>

          {/* Sticky Bottom Action Footer */}
          <div className="px-5 py-3.5 border-t border-slate-100 bg-slate-50/90 flex items-center gap-3">
            <button
              type="button"
              onClick={handleGeneratePdf}
              disabled={generatingPdf || !activeTemplate}
              data-testid="generate-pdf-btn"
              className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-sm py-3 px-5 shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              <FileCheck2 className="w-4 h-4" />
              {generatingPdf ? 'Creating PDF...' : 'Create Filled PDF'}
            </button>

            {hasAnyValue && (
              <button
                type="button"
                onClick={handleClearForm}
                className="px-3.5 py-3 rounded-xl text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-200/70 transition cursor-pointer"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* RIGHT: Sticky Live PDF Preview */}
        <div className="lg:col-span-6 lg:sticky lg:top-18">
          <PdfPreviewPane
            activeTemplate={activeTemplate}
            generatedPdfUrl={generatedPdfUrl}
            previewPage={previewPage}
            totalTemplatePages={totalTemplatePages}
            mappedPages={mappedPages}
            onPreviewPageChange={setPreviewPage}
            onResetPreview={() => {
              if (generatedPdfUrl) URL.revokeObjectURL(generatedPdfUrl);
              setGeneratedPdfUrl(null);
              setGeneratedPdfBlob(null);
            }}
            onDownloadPdf={handleDownloadPdf}
            onSharePdf={handleSharePdf}
            onOpenMapper={onOpenMapper}
          />
        </div>
      </div>

      <SavedProfilesDrawer
        isOpen={profilesOpen}
        onClose={() => setProfilesOpen(false)}
        currentFormData={formData}
        onApplyProfile={handleApplyProfile}
      />
    </div>
  );
}

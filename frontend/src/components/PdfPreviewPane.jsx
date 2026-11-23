import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  Move,
  RotateCcw,
  Save,
  Share2,
  Sliders,
  Undo2,
} from 'lucide-react';
import PdfPageCanvas from './PdfPageCanvas';
import {
  checkboxMatchesValue,
  humanizeFieldKey,
  isSignatureLikeKey,
} from '../constants';

const ZOOM_LEVELS = [1, 1.5, 2];

function clamp01(val, min = 0, max = 1) {
  return Number(Math.max(min, Math.min(max, val)).toFixed(4));
}

function resolveMediaUrl(fieldKey, mediaPreviews) {
  if (!mediaPreviews) return null;
  if (mediaPreviews[fieldKey]) return mediaPreviews[fieldKey];
  const fkLow = String(fieldKey || '').toLowerCase();
  if (fkLow.includes('witness') && mediaPreviews.witness_signature) {
    return mediaPreviews.witness_signature;
  }
  if (isSignatureLikeKey(fkLow) && mediaPreviews.applicant_signature) {
    return mediaPreviews.applicant_signature;
  }
  if (
    (fkLow.includes('photo') || fkLow.includes('avatar') || fkLow.includes('passport')) &&
    mediaPreviews.profile_photo
  ) {
    return mediaPreviews.profile_photo;
  }
  return null;
}

function getMappingKey(m, idx) {
  return m?.id != null ? `id_${m.id}` : `idx_${idx}_${m?.field_key || 'f'}`;
}

export default function PdfPreviewPane({
  activeTemplate,
  draftMappings = [],
  formData = {},
  mediaPreviews = {},
  generatedPdfUrl,
  previewPage,
  totalTemplatePages,
  mappedPages,
  adjustMode = false,
  hasPositionEdits = false,
  generatingPdf = false,
  savingPositions = false,
  onPreviewPageChange,
  onToggleAdjustMode,
  onDraftMappingsChange,
  onResetPositions,
  onApplyAndRestamp,
  onSavePositionsToTemplate,
  onResetPreview,
  onDownloadPdf,
  onSharePdf,
  onOpenMapper,
}) {
  const [showBoxes, setShowBoxes] = useState(true);
  const [showUnfilledInMove, setShowUnfilledInMove] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [selectedKey, setSelectedKey] = useState(null);
  const [undoStack, setUndoStack] = useState([]);
  const [interaction, setInteraction] = useState(null);
  const [pageDims, setPageDims] = useState({ width: 595, height: 842 });
  const [surfaceWidthPx, setSurfaceWidthPx] = useState(520);

  const surfaceWrapRef = useRef(null);

  const activeMappingsList = draftMappings.length
    ? draftMappings
    : activeTemplate?.mappings || [];

  const pageMappings = useMemo(
    () =>
      activeMappingsList
        .map((m, idx) => ({ mapping: m, overlayKey: getMappingKey(m, idx), globalIdx: idx }))
        .filter((item) => (item.mapping.page_number || 1) === previewPage),
    [activeMappingsList, previewPage]
  );

  const isMappingFilled = useCallback(
    (m) => {
      if (m.type === 'checkbox') {
        return checkboxMatchesValue(formData[m.field_key], m.match_value);
      }
      if (m.type === 'image') {
        return Boolean(resolveMediaUrl(m.field_key, mediaPreviews));
      }
      const val = formData[m.field_key];
      return val !== null && val !== undefined && String(val).trim() !== '';
    },
    [formData, mediaPreviews]
  );

  const filledPageItems = useMemo(
    () => pageMappings.filter((item) => isMappingFilled(item.mapping)),
    [pageMappings, isMappingFilled]
  );

  const visibleAdjustItems = useMemo(() => {
    if (showUnfilledInMove || filledPageItems.length === 0) return pageMappings;
    return filledPageItems;
  }, [showUnfilledInMove, filledPageItems, pageMappings]);

  // Reset per-session move state when leaving adjust mode or changing document
  useEffect(() => {
    if (!adjustMode) {
      setSelectedKey(null);
      setInteraction(null);
      setZoom(1);
      setUndoStack([]);
    }
  }, [adjustMode, activeTemplate?.id]);

  // Measure rendered PDF canvas width to scale live text preview fonts accurately
  useEffect(() => {
    const surface = surfaceWrapRef.current?.querySelector(
      '[data-testid="pdf-interactive-surface"]'
    );
    const updateWidth = () => {
      if (surface) {
        const w = surface.getBoundingClientRect().width;
        if (w > 40) setSurfaceWidthPx(w);
      }
    };
    updateWidth();
    let observer = null;
    if (surface && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateWidth);
      observer.observe(surface);
    }
    window.addEventListener('resize', updateWidth);
    return () => {
      window.removeEventListener('resize', updateWidth);
      if (observer) observer.disconnect();
    };
  }, [adjustMode, zoom, previewPage, activeTemplate?.id, generatedPdfUrl]);

  const pushUndoSnapshot = useCallback((snapshot) => {
    setUndoStack((prev) => [...prev.slice(-24), snapshot.map((m) => ({ ...m }))]);
  }, []);

  const handleUndo = useCallback(() => {
    setUndoStack((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      if (onDraftMappingsChange) onDraftMappingsChange(last);
      return prev.slice(0, -1);
    });
  }, [onDraftMappingsChange]);

  const nudgeSelected = useCallback(
    (dx, dy) => {
      if (!selectedKey || !onDraftMappingsChange) return;
      pushUndoSnapshot(activeMappingsList);
      const next = activeMappingsList.map((m, idx) => {
        if (getMappingKey(m, idx) !== selectedKey) return m;
        const maxX = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.width_pct || 0.04));
        const maxY = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.height_pct || 0.02));
        return {
          ...m,
          x_pct: clamp01(m.x_pct + dx, 0, maxX),
          y_pct: clamp01(m.y_pct + dy, 0, maxY),
          detection_source: 'manual',
          confidence: 1.0,
        };
      });
      onDraftMappingsChange(next);
    },
    [selectedKey, activeMappingsList, onDraftMappingsChange, pushUndoSnapshot]
  );

  const adjustSelectedFontSize = useCallback(
    (delta) => {
      if (!selectedKey || !onDraftMappingsChange) return;
      pushUndoSnapshot(activeMappingsList);
      const next = activeMappingsList.map((m, idx) => {
        if (getMappingKey(m, idx) !== selectedKey) return m;
        const cur = Number(m.font_size || 10);
        return {
          ...m,
          font_size: Number(Math.max(6, Math.min(24, cur + delta)).toFixed(1)),
        };
      });
      onDraftMappingsChange(next);
    },
    [selectedKey, activeMappingsList, onDraftMappingsChange, pushUndoSnapshot]
  );

  // Keyboard arrow nudging & Ctrl+Z undo while Move Answers mode is open
  useEffect(() => {
    if (!adjustMode) return undefined;
    const onKeyDown = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        handleUndo();
        return;
      }
      if (!selectedKey) return;

      const step = e.shiftKey ? 0.008 : 0.002;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        nudgeSelected(-step, 0);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        nudgeSelected(step, 0);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        nudgeSelected(0, -step);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        nudgeSelected(0, step);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [adjustMode, selectedKey, handleUndo, nudgeSelected]);

  const getNormalizedPoint = (e) => {
    const surface = surfaceWrapRef.current?.querySelector(
      '[data-testid="pdf-interactive-surface"]'
    );
    if (!surface) return { x: 0, y: 0 };
    const rect = surface.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height))),
    };
  };

  const handleOverlayPointerDown = (e, item, mode = 'move') => {
    e.stopPropagation();
    if (e.button !== undefined && e.button !== 0) return;
    const pt = getNormalizedPoint(e);
    setSelectedKey(item.overlayKey);
    pushUndoSnapshot(activeMappingsList);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setInteraction({
      mode,
      overlayKey: item.overlayKey,
      startX: pt.x,
      startY: pt.y,
      origX: item.mapping.x_pct,
      origY: item.mapping.y_pct,
      origW: item.mapping.width_pct || 0.2,
      origH: item.mapping.height_pct || 0.028,
    });
  };

  const handleSurfacePointerMove = (e) => {
    if (!interaction || !onDraftMappingsChange) return;
    const pt = getNormalizedPoint(e);
    const dx = pt.x - interaction.startX;
    const dy = pt.y - interaction.startY;

    const next = activeMappingsList.map((m, idx) => {
      if (getMappingKey(m, idx) !== interaction.overlayKey) return m;
      if (interaction.mode === 'move') {
        const maxX = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.width_pct || 0.04));
        const maxY = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.height_pct || 0.02));
        return {
          ...m,
          x_pct: clamp01(interaction.origX + dx, 0, maxX),
          y_pct: clamp01(interaction.origY + dy, 0, maxY),
          detection_source: 'manual',
          confidence: 1.0,
        };
      }
      if (interaction.mode === 'resize-w') {
        const origRight = interaction.origX + interaction.origW;
        const nextX = clamp01(interaction.origX + dx, 0, Math.max(0, origRight - 0.025));
        const nextW = clamp01(origRight - nextX, 0.025, 1 - nextX);
        return {
          ...m,
          x_pct: nextX,
          width_pct: nextW,
          detection_source: 'manual',
          confidence: 1.0,
        };
      }
      return {
        ...m,
        width_pct: clamp01(interaction.origW + dx, 0.025, 1 - interaction.origX),
        height_pct: clamp01(interaction.origH + dy, 0.014, 1 - interaction.origY),
        detection_source: 'manual',
        confidence: 1.0,
      };
    });
    onDraftMappingsChange(next);
  };

  const handleSurfacePointerUp = () => {
    if (interaction) setInteraction(null);
  };

  const selectedItem = useMemo(
    () =>
      activeMappingsList
        .map((m, idx) => ({ mapping: m, overlayKey: getMappingKey(m, idx) }))
        .find((item) => item.overlayKey === selectedKey) || null,
    [activeMappingsList, selectedKey]
  );

  const canvasScale = surfaceWidthPx / Math.max(1, pageDims.width || 595);

  return (
    <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-4 space-y-3.5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900">
            {adjustMode
              ? 'Move Answers'
              : generatedPdfUrl
              ? 'Filled PDF Ready'
              : 'Preview'}
          </h2>
          {generatedPdfUrl && !adjustMode && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              Stamped
            </span>
          )}
          {adjustMode && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200">
              Drag or Arrow-Nudge
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {activeTemplate && activeMappingsList.length > 0 && onToggleAdjustMode && (
            <button
              type="button"
              onClick={onToggleAdjustMode}
              disabled={generatingPdf}
              data-testid="toggle-move-answers-btn"
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-lg border transition cursor-pointer ${
                adjustMode
                  ? 'bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-600'
                  : 'bg-amber-50 hover:bg-amber-100 text-amber-900 border-amber-200'
              }`}
            >
              {adjustMode ? <Check className="w-3.5 h-3.5" /> : <Move className="w-3.5 h-3.5" />}
              {adjustMode
                ? generatingPdf
                  ? 'Updating...'
                  : hasPositionEdits
                  ? 'Done & Apply'
                  : 'Done'
                : 'Move Answers'}
            </button>
          )}

          {generatedPdfUrl && !adjustMode ? (
            <button
              type="button"
              onClick={onResetPreview}
              className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-900 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Back to blank
            </button>
          ) : activeTemplate && !adjustMode ? (
            <>
              <button
                type="button"
                onClick={() => setShowBoxes((v) => !v)}
                className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-lg border transition cursor-pointer ${
                  showBoxes
                    ? 'bg-slate-900 text-white border-slate-900'
                    : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                }`}
              >
                {showBoxes ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                Show boxes
              </button>
              {onOpenMapper && (
                <button
                  type="button"
                  onClick={onOpenMapper}
                  className="inline-flex items-center gap-1 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 px-2.5 py-1 rounded-lg transition cursor-pointer"
                >
                  <Sliders className="w-3.5 h-3.5" />
                  Adjust
                </button>
              )}
            </>
          ) : null}
        </div>
      </div>

      {/* Move Answers Action & Zoom Toolbar */}
      {adjustMode && (
        <div
          className="rounded-xl border border-amber-200 bg-amber-50/60 p-2.5 space-y-2"
          data-testid="move-answers-toolbar"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1">
              <span className="text-[11px] font-semibold text-slate-600 mr-1">Zoom:</span>
              {ZOOM_LEVELS.map((z) => (
                <button
                  key={z}
                  type="button"
                  onClick={() => setZoom(z)}
                  className={`px-2 py-0.5 rounded-md text-[11px] font-bold cursor-pointer transition ${
                    zoom === z
                      ? 'bg-slate-900 text-white'
                      : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-100'
                  }`}
                >
                  {z}x
                </button>
              ))}
              {filledPageItems.length > 0 && filledPageItems.length < pageMappings.length && (
                <button
                  type="button"
                  onClick={() => setShowUnfilledInMove((v) => !v)}
                  className={`ml-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold border cursor-pointer transition ${
                    showUnfilledInMove
                      ? 'bg-slate-900 text-white border-slate-900'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100'
                  }`}
                >
                  {showUnfilledInMove ? 'Filled only' : 'Show all slots'}
                </button>
              )}
            </div>

            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                type="button"
                disabled={undoStack.length === 0}
                onClick={handleUndo}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 disabled:opacity-40 cursor-pointer"
                title="Undo last move (Ctrl+Z)"
              >
                <Undo2 className="w-3 h-3" />
                Undo
              </button>
              {hasPositionEdits && onResetPositions && (
                <button
                  type="button"
                  onClick={() => {
                    setUndoStack([]);
                    onResetPositions();
                  }}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold bg-white border border-slate-200 text-slate-600 hover:text-slate-900 cursor-pointer"
                >
                  <RotateCcw className="w-3 h-3" />
                  Reset
                </button>
              )}
              {onSavePositionsToTemplate && hasPositionEdits && (
                <button
                  type="button"
                  disabled={savingPositions}
                  onClick={onSavePositionsToTemplate}
                  data-testid="save-positions-template-btn"
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-900 hover:bg-slate-800 text-white cursor-pointer disabled:opacity-50"
                  title="Persist moved positions for future fills of this PDF"
                >
                  <Save className="w-3 h-3 text-amber-400" />
                  {savingPositions ? 'Saving...' : 'Save as Default'}
                </button>
              )}
              {onApplyAndRestamp && (
                <button
                  type="button"
                  disabled={generatingPdf}
                  onClick={onApplyAndRestamp}
                  data-testid="apply-positions-btn"
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-bold bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer disabled:opacity-50"
                >
                  <Check className="w-3 h-3" />
                  {generatingPdf ? 'Stamping...' : 'Apply & Preview PDF'}
                </button>
              )}
            </div>
          </div>

          {/* Selected Item Fine Nudge Controls */}
          {selectedItem ? (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-amber-200/70">
              <span className="text-[11px] font-semibold text-slate-800 truncate max-w-[240px]">
                Selected:{' '}
                {selectedItem.mapping.label ||
                  humanizeFieldKey(selectedItem.mapping.field_key)}
                {selectedItem.mapping.type === 'checkbox' && selectedItem.mapping.match_value
                  ? ` (${selectedItem.mapping.match_value})`
                  : ''}
              </span>

              <div className="flex items-center gap-1">
                {selectedItem.mapping.type !== 'checkbox' &&
                  selectedItem.mapping.type !== 'image' && (
                    <div className="flex items-center gap-1 mr-2">
                      <button
                        type="button"
                        onClick={() => adjustSelectedFontSize(-0.5)}
                        className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-[11px] font-bold text-slate-700 hover:bg-slate-100 cursor-pointer"
                        title="Smaller font"
                      >
                        A-
                      </button>
                      <button
                        type="button"
                        onClick={() => adjustSelectedFontSize(0.5)}
                        className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-[11px] font-bold text-slate-700 hover:bg-slate-100 cursor-pointer"
                        title="Larger font"
                      >
                        A+
                      </button>
                    </div>
                  )}
                <button
                  type="button"
                  onClick={() => nudgeSelected(-0.002, 0)}
                  className="p-1 rounded bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 cursor-pointer"
                  title="Nudge Left"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => nudgeSelected(0, -0.002)}
                  className="p-1 rounded bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 cursor-pointer"
                  title="Nudge Up"
                >
                  <ArrowUp className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => nudgeSelected(0, 0.002)}
                  className="p-1 rounded bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 cursor-pointer"
                  title="Nudge Down"
                >
                  <ArrowDown className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => nudgeSelected(0.002, 0)}
                  className="p-1 rounded bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 cursor-pointer"
                  title="Nudge Right"
                >
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <p className="text-[11px] text-amber-900/80">
              Tap or drag any answer or checkmark on the page below to nudge it into place.
            </p>
          )}
        </div>
      )}

      {/* Download & Share Bar when Stamped and not editing positions */}
      {generatedPdfUrl && !adjustMode && (
        <div className="space-y-1.5">
          <div className="grid grid-cols-2 gap-2.5" data-testid="pdf-actions-bar">
            <button
              type="button"
              onClick={onDownloadPdf}
              data-testid="download-pdf-btn"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs py-2.5 px-3 shadow-xs transition cursor-pointer"
            >
              <Download className="w-4 h-4 text-amber-400" />
              Download PDF
            </button>
            <button
              type="button"
              onClick={onSharePdf}
              data-testid="share-pdf-btn"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs py-2.5 px-3 shadow-xs transition cursor-pointer"
            >
              <Share2 className="w-4 h-4" />
              Share
            </button>
          </div>
          {onToggleAdjustMode && activeMappingsList.length > 0 && (
            <p className="text-[11px] text-slate-500 text-center">
              Need tighter placement? Click{' '}
              <button
                type="button"
                onClick={onToggleAdjustMode}
                className="font-semibold text-amber-800 underline cursor-pointer"
              >
                Move Answers
              </button>{' '}
              to fine-tune checkmarks or text before downloading.
            </p>
          )}
        </div>
      )}

      {/* Minimal Multi-Page Navigation */}
      {totalTemplatePages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-100 rounded-xl px-3 py-1.5 text-xs">
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={previewPage <= 1}
              onClick={() => onPreviewPageChange(Math.max(1, previewPage - 1))}
              className="p-1 rounded-lg hover:bg-white text-slate-700 disabled:opacity-40 cursor-pointer"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-semibold text-slate-700 px-1.5">
              {previewPage} / {totalTemplatePages}
            </span>
            <button
              type="button"
              disabled={previewPage >= totalTemplatePages}
              onClick={() =>
                onPreviewPageChange(Math.min(totalTemplatePages, previewPage + 1))
              }
              className="p-1 rounded-lg hover:bg-white text-slate-700 disabled:opacity-40 cursor-pointer"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center gap-1 flex-wrap">
            {mappedPages.map((pg) => (
              <button
                key={pg}
                type="button"
                onClick={() => onPreviewPageChange(pg)}
                className={`px-2 py-0.5 rounded-md text-[11px] font-semibold transition cursor-pointer ${
                  previewPage === pg
                    ? 'bg-slate-900 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200'
                }`}
              >
                P.{pg}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* PDF Canvas */}
      {generatedPdfUrl && !adjustMode ? (
        <div data-testid="stamped-pdf-preview">
          <PdfPageCanvas pdfUrl={generatedPdfUrl} pageNumber={previewPage} />
        </div>
      ) : activeTemplate ? (
        <div
          ref={surfaceWrapRef}
          data-testid={adjustMode ? 'move-answers-preview' : 'blank-template-preview'}
          className="overflow-x-auto"
          onPointerMove={handleSurfacePointerMove}
          onPointerUp={handleSurfacePointerUp}
          onPointerCancel={handleSurfacePointerUp}
          onPointerDown={(e) => {
            if (adjustMode && !e.target.closest('[data-answer-overlay="true"]')) {
              setSelectedKey(null);
            }
          }}
        >
          <PdfPageCanvas
            pdfUrl={`/api/templates/${activeTemplate.id}/pdf`}
            fallbackImageUrl={`/api/templates/${activeTemplate.id}/page-image/${previewPage}`}
            pageNumber={previewPage}
            zoom={adjustMode ? zoom : 1}
            touchNone={adjustMode}
            onPageDimensions={(dims) =>
              setPageDims({ width: dims.width || 595, height: dims.height || 842 })
            }
          >
            {adjustMode
              ? visibleAdjustItems.map(({ mapping: m, overlayKey }) => {
                  const isSel = selectedKey === overlayKey;
                  const lbl = m.label || humanizeFieldKey(m.field_key);

                  if (m.type === 'checkbox') {
                    const isChecked = isMappingFilled(m);
                    return (
                      <div
                        key={overlayKey}
                        data-answer-overlay="true"
                        onPointerDown={(e) =>
                          handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'move')
                        }
                        style={{
                          left: `${m.x_pct * 100}%`,
                          top: `${m.y_pct * 100}%`,
                        }}
                        title={`${lbl}: ${m.match_value} (drag to position)`}
                        className={`absolute -translate-x-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full cursor-move touch-none transition-shadow ${
                          isSel
                            ? 'ring-2 ring-amber-500 bg-amber-300/25 z-20'
                            : 'hover:bg-blue-400/20 z-10'
                        }`}
                      >
                        {isChecked ? (
                          <svg
                            viewBox="0 0 16 16"
                            className="w-3.5 h-3.5 pointer-events-none drop-shadow-[0_0_1px_rgba(255,255,255,0.9)]"
                            fill="none"
                          >
                            <path
                              d="M3 8.5L6.2 12L13 4"
                              stroke="#0a2673"
                              strokeWidth="2.4"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        ) : (
                          <span className="w-2.5 h-2.5 rounded-sm border border-emerald-600/80 bg-emerald-400/25 pointer-events-none" />
                        )}
                      </div>
                    );
                  }

                  if (m.type === 'image') {
                    const imgUrl = resolveMediaUrl(m.field_key, mediaPreviews);
                    return (
                      <div
                        key={overlayKey}
                        data-answer-overlay="true"
                        onPointerDown={(e) =>
                          handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'move')
                        }
                        style={{
                          left: `${m.x_pct * 100}%`,
                          top: `${m.y_pct * 100}%`,
                          width: `${(m.width_pct || 0.2) * 100}%`,
                          height: `${(m.height_pct || 0.06) * 100}%`,
                        }}
                        title={`${lbl} (drag or resize)`}
                        className={`absolute rounded-[3px] cursor-move touch-none flex items-center justify-center overflow-hidden ${
                          isSel
                            ? 'border-2 border-amber-500 bg-amber-100/20 z-20'
                            : 'border border-dashed border-amber-500/80 bg-amber-50/15 z-10'
                        }`}
                      >
                        {imgUrl ? (
                          <img
                            src={imgUrl}
                            alt={lbl}
                            className="w-full h-full object-contain pointer-events-none"
                            draggable={false}
                          />
                        ) : (
                          <span className="text-[10px] font-semibold text-amber-800 px-1 truncate pointer-events-none">
                            {lbl}
                          </span>
                        )}
                        <div
                          data-answer-overlay="true"
                          onPointerDown={(e) =>
                            handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'resize')
                          }
                          className="absolute right-0 bottom-0 w-3 h-3 bg-amber-500 rounded-tl cursor-nwse-resize"
                          title="Drag to resize"
                        />
                      </div>
                    );
                  }

                  const textVal = formData[m.field_key];
                  const hasText =
                    textVal !== null && textVal !== undefined && String(textVal).trim() !== '';
                  const isMulti =
                    m.type === 'multiline' || (hasText && String(textVal).includes('\n'));
                  const scaledPx = Math.max(
                    8,
                    Math.round(Number(m.font_size || 10) * canvasScale * 10) / 10
                  );

                  return (
                    <div
                      key={overlayKey}
                      data-answer-overlay="true"
                      onPointerDown={(e) =>
                        handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'move')
                      }
                      style={{
                        left: `${m.x_pct * 100}%`,
                        top: `${m.y_pct * 100}%`,
                        width: `${(m.width_pct || 0.25) * 100}%`,
                        height: `${(m.height_pct || 0.028) * 100}%`,
                        fontSize: `${scaledPx}px`,
                        lineHeight: 1.2,
                      }}
                      title={`${lbl} (drag or resize)`}
                      className={`absolute rounded-[3px] cursor-move touch-none pl-2.5 pr-1 flex ${
                        isMulti ? 'items-start pt-0.5' : 'items-center'
                      } overflow-hidden ${
                        isSel
                          ? 'border-2 border-blue-600 bg-blue-50/35 z-20'
                          : 'border border-dashed border-blue-500/75 bg-blue-50/20 z-10'
                      }`}
                    >
                      <div
                        data-answer-overlay="true"
                        onPointerDown={(e) =>
                          handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'resize-w')
                        }
                        className="absolute left-0 top-0 bottom-0 w-2 bg-blue-600/60 hover:bg-blue-600 cursor-ew-resize"
                        title="Drag left edge to adjust start"
                      />
                      <span
                        className={`pointer-events-none w-full ${
                          isMulti ? 'whitespace-pre-wrap break-words' : 'truncate'
                        } ${
                          hasText ? 'text-[#0a173d] font-medium' : 'text-blue-700/70 text-[10px]'
                        }`}
                      >
                        {hasText ? String(textVal) : lbl}
                      </span>
                      <div
                        data-answer-overlay="true"
                        onPointerDown={(e) =>
                          handleOverlayPointerDown(e, { mapping: m, overlayKey }, 'resize')
                        }
                        className="absolute right-0 bottom-0 w-2.5 h-2.5 bg-blue-600 rounded-tl cursor-nwse-resize"
                        title="Drag to resize"
                      />
                    </div>
                  );
                })
              : showBoxes &&
                pageMappings.map(({ mapping: m, overlayKey }) => {
                  const lbl = m.label || humanizeFieldKey(m.field_key);
                  if (m.type === 'checkbox') {
                    return (
                      <div
                        key={overlayKey}
                        style={{
                          left: `${m.x_pct * 100}%`,
                          top: `${m.y_pct * 100}%`,
                        }}
                        className="absolute -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-sm bg-emerald-500/25 border border-emerald-600/80 pointer-events-none"
                        title={`${lbl}: ${m.match_value}`}
                      />
                    );
                  }
                  const colorCls =
                    m.type === 'image'
                      ? 'bg-amber-400/15 border-amber-500/75'
                      : 'bg-blue-500/12 border-blue-500/70';
                  return (
                    <div
                      key={overlayKey}
                      style={{
                        left: `${m.x_pct * 100}%`,
                        top: `${m.y_pct * 100}%`,
                        width: `${(m.width_pct || 0.2) * 100}%`,
                        height: `${(m.height_pct || 0.028) * 100}%`,
                      }}
                      className={`absolute border rounded-[2px] pointer-events-none ${colorCls}`}
                      title={lbl}
                    />
                  );
                })}
          </PdfPageCanvas>
        </div>
      ) : null}
    </div>
  );
}

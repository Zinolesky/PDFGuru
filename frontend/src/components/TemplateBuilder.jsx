import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Type,
  CheckSquare,
  Image as ImageIcon,
  Save,
  Trash2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ScanSearch,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  CheckCircle2,
  X,
} from 'lucide-react';
import PdfPageCanvas from './PdfPageCanvas';
import { humanizeFieldKey, slugifyLabel } from '../constants';

let uidCounter = 1;
const makeUid = () => `map_${Date.now()}_${uidCounter++}`;

function withUids(list) {
  return (list || []).map((m) => ({
    ...m,
    _uid: m._uid || (m.id ? `db_${m.id}` : makeUid()),
  }));
}

export default function TemplateBuilder({ activeTemplate, onTemplatesRefresh }) {
  const [activeTool, setActiveTool] = useState('text'); // 'text' | 'checkbox' | 'image'
  const [pageNumber, setPageNumber] = useState(1);
  const [totalPages, setTotalPages] = useState(activeTemplate?.page_count || 1);
  const [mappings, setMappings] = useState(() => withUids(activeTemplate?.mappings));
  const [historyPast, setHistoryPast] = useState([]);
  const [historyFuture, setHistoryFuture] = useState([]);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  const [selectedUid, setSelectedUid] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customKeyEdited, setCustomKeyEdited] = useState(false);
  const [showQALinks, setShowQALinks] = useState(false);
  const [zoom, setZoom] = useState(1);

  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusBanner, setStatusBanner] = useState(null);

  const [interaction, setInteraction] = useState(null);
  const surfaceRef = useRef(null);

  // Sync local state when selected document changes
  useEffect(() => {
    if (activeTemplate) {
      const tplMappings = withUids(activeTemplate.mappings);
      setMappings(tplMappings);
      setHistoryPast([]);
      setHistoryFuture([]);
      setHasUnsavedChanges(false);
      setSelectedUid(null);
      setTotalPages(activeTemplate.page_count || 1);
      const firstMappedPage =
        tplMappings.length > 0
          ? Math.min(...tplMappings.map((m) => m.page_number || 1))
          : 1;
      setPageNumber(firstMappedPage);
    }
  }, [activeTemplate?.id]);

  // Reset per-selection Advanced panel state when changing selected box
  useEffect(() => {
    setShowAdvanced(false);
    setCustomKeyEdited(false);
  }, [selectedUid]);

  useEffect(() => {
    if (!statusBanner || statusBanner.type === 'error') return undefined;
    const t = setTimeout(() => setStatusBanner(null), 4000);
    return () => clearTimeout(t);
  }, [statusBanner]);

  const commitMappings = useCallback((updater) => {
    setMappings((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      setHistoryPast((past) => [...past.slice(-29), prev]);
      setHistoryFuture([]);
      setHasUnsavedChanges(true);
      return next;
    });
  }, []);

  const handleUndo = useCallback(() => {
    setHistoryPast((past) => {
      if (past.length === 0) return past;
      const previous = past[past.length - 1];
      setMappings((curr) => {
        setHistoryFuture((f) => [curr, ...f.slice(0, 29)]);
        return previous;
      });
      setHasUnsavedChanges(true);
      return past.slice(0, -1);
    });
  }, []);

  const handleRedo = useCallback(() => {
    setHistoryFuture((future) => {
      if (future.length === 0) return future;
      const next = future[0];
      setMappings((curr) => {
        setHistoryPast((p) => [...p.slice(-29), curr]);
        return next;
      });
      setHasUnsavedChanges(true);
      return future.slice(1);
    });
  }, []);

  // Keyboard shortcuts: Undo/Redo, Delete, Arrow nudging
  useEffect(() => {
    const onKeyDown = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) handleRedo();
        else handleUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        handleRedo();
        return;
      }
      if (!selectedUid) return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        commitMappings((prev) => prev.filter((m) => m._uid !== selectedUid));
        setSelectedUid(null);
        return;
      }

      const step = e.shiftKey ? 0.01 : 0.002;
      let dx = 0;
      let dy = 0;
      if (e.key === 'ArrowLeft') dx = -step;
      else if (e.key === 'ArrowRight') dx = step;
      else if (e.key === 'ArrowUp') dy = -step;
      else if (e.key === 'ArrowDown') dy = step;
      else return;

      e.preventDefault();
      commitMappings((prev) =>
        prev.map((m) =>
          m._uid === selectedUid
            ? {
                ...m,
                x_pct: Number(Math.max(0, Math.min(0.99, m.x_pct + dx)).toFixed(4)),
                y_pct: Number(Math.max(0, Math.min(0.99, m.y_pct + dy)).toFixed(4)),
              }
            : m
        )
      );
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedUid, commitMappings, handleUndo, handleRedo]);

  const selectedMapping = mappings.find((m) => m._uid === selectedUid) || null;

  const getNormalizedCoords = (e) => {
    const surface = surfaceRef.current?.querySelector('[data-testid="pdf-interactive-surface"]');
    if (!surface) return { x: 0, y: 0 };
    const rect = surface.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    return { x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) };
  };

  const handleSurfacePointerDown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target.closest('[data-mapping-badge="true"]')) return;

    const pt = getNormalizedCoords(e);
    setSelectedUid(null);

    if (activeTool === 'checkbox') {
      const uid = makeUid();
      const idx = mappings.filter((m) => m.type === 'checkbox').length + 1;
      const label = `Option ${idx}`;
      const newMapping = {
        _uid: uid,
        type: 'checkbox',
        field_key: `choice_${idx}`,
        label,
        question_text: label,
        section: null,
        match_value: 'Yes',
        x_pct: pt.x,
        y_pct: pt.y,
        width_pct: null,
        height_pct: null,
        page_number: pageNumber,
        font_size: null,
        align: 'left',
        confidence: 1.0,
        detection_source: 'manual',
      };
      commitMappings((prev) => [...prev, newMapping]);
      setSelectedUid(uid);
      return;
    }

    e.currentTarget.setPointerCapture?.(e.pointerId);
    setInteraction({
      mode: 'draw',
      startX: pt.x,
      startY: pt.y,
      currX: pt.x,
      currY: pt.y,
    });
  };

  const handleBoxPointerDown = (e, mapping, handle = 'move') => {
    e.stopPropagation();
    if (e.button !== undefined && e.button !== 0) return;
    const pt = getNormalizedCoords(e);
    setSelectedUid(mapping._uid);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setHistoryPast((past) => [...past.slice(-29), mappings]);
    setHistoryFuture([]);
    setInteraction({
      mode: handle === 'move' ? 'move' : 'resize',
      handle,
      uid: mapping._uid,
      startX: pt.x,
      startY: pt.y,
      origX: mapping.x_pct,
      origY: mapping.y_pct,
      origW: mapping.width_pct || 0.2,
      origH: mapping.height_pct || 0.03,
    });
  };

  const handleSurfacePointerMove = (e) => {
    if (!interaction) return;
    const pt = getNormalizedCoords(e);

    if (interaction.mode === 'draw') {
      setInteraction((prev) => (prev ? { ...prev, currX: pt.x, currY: pt.y } : null));
      return;
    }

    const dx = pt.x - interaction.startX;
    const dy = pt.y - interaction.startY;

    if (interaction.mode === 'move') {
      setHasUnsavedChanges(true);
      setMappings((prev) =>
        prev.map((m) => {
          if (m._uid !== interaction.uid) return m;
          const maxX = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.width_pct || 0.05));
          const maxY = m.type === 'checkbox' ? 0.99 : Math.max(0.01, 1 - (m.height_pct || 0.02));
          return {
            ...m,
            x_pct: Number(Math.max(0, Math.min(maxX, interaction.origX + dx)).toFixed(4)),
            y_pct: Number(Math.max(0, Math.min(maxY, interaction.origY + dy)).toFixed(4)),
            detection_source: 'manual',
            confidence: 1.0,
          };
        })
      );
      return;
    }

    if (interaction.mode === 'resize') {
      setHasUnsavedChanges(true);
      const { handle, origX, origY, origW, origH } = interaction;
      let nx = origX;
      let ny = origY;
      let nw = origW;
      let nh = origH;

      if (handle.includes('e')) nw = Math.max(0.025, Math.min(1 - origX, origW + dx));
      if (handle.includes('s')) nh = Math.max(0.015, Math.min(1 - origY, origH + dy));
      if (handle.includes('w')) {
        const right = origX + origW;
        nx = Math.max(0, Math.min(right - 0.025, origX + dx));
        nw = right - nx;
      }
      if (handle.includes('n')) {
        const bottom = origY + origH;
        ny = Math.max(0, Math.min(bottom - 0.015, origY + dy));
        nh = bottom - ny;
      }

      setMappings((prev) =>
        prev.map((m) =>
          m._uid === interaction.uid
            ? {
                ...m,
                x_pct: Number(nx.toFixed(4)),
                y_pct: Number(ny.toFixed(4)),
                width_pct: Number(nw.toFixed(4)),
                height_pct: Number(nh.toFixed(4)),
                detection_source: 'manual',
                confidence: 1.0,
              }
            : m
        )
      );
    }
  };

  const handleSurfacePointerUp = () => {
    if (!interaction) return;
    if (interaction.mode === 'draw') {
      const x1 = Math.min(interaction.startX, interaction.currX);
      const y1 = Math.min(interaction.startY, interaction.currY);
      let w = Math.abs(interaction.currX - interaction.startX);
      let h = Math.abs(interaction.currY - interaction.startY);

      if (w < 0.015 && h < 0.01) {
        if (activeTool === 'text') {
          w = 0.28;
          h = 0.026;
        } else {
          w = 0.22;
          h = 0.055;
        }
      }

      // Tall text boxes automatically become multiline
      const resolvedType =
        activeTool === 'image' ? 'image' : h >= 0.055 ? 'multiline' : 'text';

      const uid = makeUid();
      const idx = mappings.filter((m) => m.type === resolvedType).length + 1;
      const defaultLabel =
        resolvedType === 'image' ? `Photo / Signature ${idx}` : `Field ${idx}`;
      const defaultKey =
        resolvedType === 'image'
          ? idx === 1
            ? 'applicant_signature'
            : `custom_image_${idx}`
          : `field_${idx}`;

      const newMapping = {
        _uid: uid,
        type: resolvedType,
        field_key: defaultKey,
        label: defaultLabel,
        question_text: defaultLabel,
        section: null,
        match_value: null,
        x_pct: Number(x1.toFixed(4)),
        y_pct: Number(y1.toFixed(4)),
        width_pct: Number(Math.min(1 - x1, w).toFixed(4)),
        height_pct: Number(Math.min(1 - y1, h).toFixed(4)),
        page_number: pageNumber,
        font_size: resolvedType === 'image' ? null : 10.0,
        align: 'left',
        confidence: 1.0,
        detection_source: 'manual',
      };

      commitMappings((prev) => [...prev, newMapping]);
      setSelectedUid(uid);
    }
    setInteraction(null);
  };

  const handleUpdateSelected = (patch) => {
    if (!selectedUid) return;
    commitMappings((prev) =>
      prev.map((m) => (m._uid === selectedUid ? { ...m, ...patch } : m))
    );
  };

  const handleLabelChange = (newLabel) => {
    if (!selectedMapping) return;
    const patch = { label: newLabel };
    if (!customKeyEdited) {
      patch.field_key = slugifyLabel(newLabel);
    }
    handleUpdateSelected(patch);
  };

  const handleRemoveMapping = (uid) => {
    commitMappings((prev) => prev.filter((m) => m._uid !== uid));
    if (selectedUid === uid) setSelectedUid(null);
  };

  const handleAutoDetectInputs = async () => {
    if (!activeTemplate) return;
    setAnalyzing(true);
    setStatusBanner(null);
    try {
      const res = await fetch(`/api/templates/${activeTemplate.id}/analyze?use_vision=true`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to detect fields');
      const updated = await res.json();
      setMappings(withUids(updated.mappings));
      setHistoryPast([]);
      setHistoryFuture([]);
      setHasUnsavedChanges(false);
      setSelectedUid(null);
      await onTemplatesRefresh(updated.id);
      setStatusBanner({
        type: 'success',
        text: `Detected ${updated.mappings?.length || 0} fields.`,
      });
    } catch (err) {
      setStatusBanner({ type: 'error', text: err.message });
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSaveMappings = async () => {
    if (!activeTemplate) return;
    setSaving(true);
    setStatusBanner(null);
    try {
      const payload = mappings.map((m) => ({
        type: m.type,
        field_key: m.field_key,
        label: m.label || humanizeFieldKey(m.field_key),
        question_text: m.question_text || null,
        section: m.section || null,
        match_value: m.match_value || null,
        x_pct: Number(m.x_pct),
        y_pct: Number(m.y_pct),
        width_pct: m.width_pct != null ? Number(m.width_pct) : null,
        height_pct: m.height_pct != null ? Number(m.height_pct) : null,
        qx_pct: m.qx_pct != null ? Number(m.qx_pct) : null,
        qy_pct: m.qy_pct != null ? Number(m.qy_pct) : null,
        qw_pct: m.qw_pct != null ? Number(m.qw_pct) : null,
        qh_pct: m.qh_pct != null ? Number(m.qh_pct) : null,
        page_number: Number(m.page_number || 1),
        font_size: m.font_size != null ? Number(m.font_size) : m.type === 'image' ? null : 10.0,
        align: m.align || 'left',
        confidence: m.confidence != null ? Number(m.confidence) : 1.0,
        detection_source: m.detection_source || 'manual',
        acroform_field_name: m.acroform_field_name || null,
      }));

      const res = await fetch(`/api/templates/${activeTemplate.id}/mappings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Failed to save boxes');
      const saved = await res.json();
      setMappings(withUids(saved));
      setHasUnsavedChanges(false);
      await onTemplatesRefresh(activeTemplate.id);
      setStatusBanner({
        type: 'success',
        text: `Saved ${saved.length} boxes.`,
      });
    } catch (err) {
      setStatusBanner({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  if (!activeTemplate) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200 p-10 text-center text-sm text-slate-500">
        Upload or select a PDF above to adjust its boxes.
      </div>
    );
  }

  const pageMappings = mappings.filter((m) => (m.page_number || 1) === pageNumber);

  return (
    <div className="space-y-4">
      {/* Single Clean Toolbar */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-xs px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        {/* Left: 3 Simple Add-Box Tools */}
        <div className="flex items-center gap-1.5">
          {[
            { id: 'text', label: '+ Text', icon: Type, active: 'bg-blue-600 text-white border-blue-600' },
            { id: 'checkbox', label: '+ Checkbox', icon: CheckSquare, active: 'bg-emerald-600 text-white border-emerald-600' },
            { id: 'image', label: '+ Photo / Sig', icon: ImageIcon, active: 'bg-amber-600 text-white border-amber-600' },
          ].map((tool) => {
            const Icon = tool.icon;
            return (
              <button
                key={tool.id}
                type="button"
                onClick={() => setActiveTool(tool.id)}
                data-testid={`tool-${tool.id}-btn`}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition cursor-pointer ${
                  activeTool === tool.id
                    ? `${tool.active} shadow-xs`
                    : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tool.label}
              </button>
            );
          })}
        </div>

        {/* Center: Undo/Redo, Zoom, Page Nav */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 bg-slate-100 rounded-xl p-1">
            <button
              type="button"
              onClick={handleUndo}
              disabled={historyPast.length === 0}
              title="Undo (Ctrl+Z)"
              className="p-1.5 rounded-lg hover:bg-white text-slate-700 disabled:opacity-35 cursor-pointer"
            >
              <Undo2 className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={handleRedo}
              disabled={historyFuture.length === 0}
              title="Redo (Ctrl+Y)"
              className="p-1.5 rounded-lg hover:bg-white text-slate-700 disabled:opacity-35 cursor-pointer"
            >
              <Redo2 className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex items-center gap-1 bg-slate-100 rounded-xl px-1.5 py-1 text-xs">
            <button
              type="button"
              onClick={() => setZoom((z) => Math.max(0.75, Number((z - 0.25).toFixed(2))))}
              className="p-1 hover:bg-white rounded-lg text-slate-700 cursor-pointer"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="font-mono text-[11px] font-semibold w-10 text-center text-slate-700">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoom((z) => Math.min(2.0, Number((z + 0.25).toFixed(2))))}
              className="p-1 hover:bg-white rounded-lg text-slate-700 cursor-pointer"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center gap-1 bg-slate-100 rounded-xl px-1.5 py-1 text-xs">
              <button
                type="button"
                disabled={pageNumber <= 1}
                onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
                className="p-1 hover:bg-white rounded-lg text-slate-700 disabled:opacity-35 cursor-pointer"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-semibold text-slate-700 px-1">
                {pageNumber} / {totalPages}
              </span>
              <button
                type="button"
                disabled={pageNumber >= totalPages}
                onClick={() => setPageNumber((p) => Math.min(totalPages, p + 1))}
                className="p-1 hover:bg-white rounded-lg text-slate-700 disabled:opacity-35 cursor-pointer"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* Right: Re-detect + Save */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleAutoDetectInputs}
            disabled={analyzing}
            className="inline-flex items-center gap-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-xs px-3 py-2 transition cursor-pointer disabled:opacity-50"
          >
            <ScanSearch className="w-3.5 h-3.5 text-emerald-600" />
            {analyzing ? 'Scanning...' : 'Re-detect'}
          </button>

          <button
            type="button"
            onClick={handleSaveMappings}
            disabled={saving}
            data-testid="save-mappings-btn"
            className={`inline-flex items-center gap-1.5 rounded-xl font-semibold text-xs px-4 py-2 shadow-xs transition cursor-pointer disabled:opacity-50 ${
              hasUnsavedChanges
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white ring-2 ring-emerald-500/30'
                : 'bg-slate-900 hover:bg-slate-800 text-white'
            }`}
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? 'Saving...' : hasUnsavedChanges ? 'Save *' : 'Save'}
          </button>
        </div>
      </div>

      {statusBanner && (
        <div
          className={`rounded-xl px-4 py-2.5 text-xs font-medium flex items-center justify-between border ${
            statusBanner.type === 'error'
              ? 'bg-red-50 border-red-200 text-red-800'
              : 'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{statusBanner.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setStatusBanner(null)}
            className="p-0.5 opacity-70 hover:opacity-100 cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Main Canvas (9 cols) + Slim Sidebar (3 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Interactive PDF Canvas */}
        <div className="lg:col-span-9">
          <div
            ref={surfaceRef}
            className="overflow-auto max-h-[82vh] rounded-2xl border border-slate-200 bg-slate-200/60 p-3"
          >
            <div className="cursor-crosshair">
              <PdfPageCanvas
                pdfUrl={`/api/templates/${activeTemplate.id}/pdf`}
                fallbackImageUrl={`/api/templates/${activeTemplate.id}/page-image/${pageNumber}`}
                pageNumber={pageNumber}
                zoom={zoom}
                touchNone
                onPageDimensions={({ numPages }) => setTotalPages(numPages)}
                interactiveProps={{
                  onPointerDown: handleSurfacePointerDown,
                  onPointerMove: handleSurfacePointerMove,
                  onPointerUp: handleSurfacePointerUp,
                  onPointerCancel: handleSurfacePointerUp,
                }}
              >
                {/* Optional Question -> Answer SVG Connectors (off by default) */}
                {showQALinks && (
                  <svg
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    className="absolute inset-0 w-full h-full pointer-events-none z-0"
                  >
                    {pageMappings.map((m) => {
                      if (m.qx_pct == null || m.qy_pct == null) return null;
                      const qcx = (m.qx_pct + (m.qw_pct || 0.08) * 0.5) * 100;
                      const qcy = (m.qy_pct + (m.qh_pct || 0.015) * 0.5) * 100;
                      const acx =
                        m.type === 'checkbox'
                          ? m.x_pct * 100
                          : (m.x_pct + (m.width_pct || 0.1) * 0.5) * 100;
                      const acy =
                        m.type === 'checkbox'
                          ? m.y_pct * 100
                          : (m.y_pct + (m.height_pct || 0.02) * 0.5) * 100;
                      return (
                        <g key={`qa_${m._uid}`}>
                          <rect
                            x={m.qx_pct * 100}
                            y={m.qy_pct * 100}
                            width={(m.qw_pct || 0.08) * 100}
                            height={(m.qh_pct || 0.015) * 100}
                            fill="rgba(147, 51, 234, 0.08)"
                            stroke="rgba(147, 51, 234, 0.55)"
                            strokeWidth="0.2"
                            strokeDasharray="0.6 0.4"
                          />
                          <line
                            x1={qcx}
                            y1={qcy}
                            x2={acx}
                            y2={acy}
                            stroke="rgba(147, 51, 234, 0.45)"
                            strokeWidth="0.22"
                            strokeDasharray="0.5 0.4"
                          />
                        </g>
                      );
                    })}
                  </svg>
                )}

                {/* Answer Boxes */}
                {pageMappings.map((m) => {
                  const displayLbl = m.label || humanizeFieldKey(m.field_key);
                  const isSelected = m._uid === selectedUid;

                  if (m.type === 'checkbox') {
                    return (
                      <div
                        key={m._uid}
                        data-mapping-badge="true"
                        onPointerDown={(e) => handleBoxPointerDown(e, m, 'move')}
                        style={{
                          left: `${m.x_pct * 100}%`,
                          top: `${m.y_pct * 100}%`,
                        }}
                        className={`absolute -translate-x-1/2 -translate-y-1/2 w-5 h-5 rounded-sm border-2 flex items-center justify-center cursor-grab active:cursor-grabbing ${
                          isSelected
                            ? 'bg-emerald-500/60 border-slate-950 ring-2 ring-indigo-500 z-30'
                            : 'bg-emerald-500/35 border-emerald-600 z-20'
                        }`}
                        title={`${displayLbl}: ${m.match_value}`}
                      >
                        <span className="text-[10px] font-bold text-emerald-950 pointer-events-none">
                          ✓
                        </span>
                      </div>
                    );
                  }

                  const isImage = m.type === 'image';
                  const isMulti = m.type === 'multiline';
                  const colorCls = isImage
                    ? 'bg-amber-500/20 border-amber-600 text-amber-950'
                    : isMulti
                    ? 'bg-indigo-500/15 border-indigo-600 text-indigo-950'
                    : 'bg-blue-500/15 border-blue-600 text-blue-950';

                  return (
                    <div
                      key={m._uid}
                      data-mapping-badge="true"
                      onPointerDown={(e) => handleBoxPointerDown(e, m, 'move')}
                      style={{
                        left: `${m.x_pct * 100}%`,
                        top: `${m.y_pct * 100}%`,
                        width: `${(m.width_pct || 0.2) * 100}%`,
                        height: `${(m.height_pct || 0.03) * 100}%`,
                      }}
                      className={`absolute border flex items-center px-1 cursor-grab active:cursor-grabbing transition ${colorCls} ${
                        isSelected ? 'ring-2 ring-indigo-600 border-slate-950 z-30' : 'z-20'
                      }`}
                      title={displayLbl}
                    >
                      <span className="text-[9px] font-bold truncate leading-none bg-white/85 px-1 py-0.5 rounded pointer-events-none">
                        {displayLbl}
                      </span>

                      {isSelected &&
                        ['nw', 'ne', 'sw', 'se'].map((corner) => {
                          const posCls =
                            corner === 'nw'
                              ? '-top-1.5 -left-1.5 cursor-nwse-resize'
                              : corner === 'ne'
                              ? '-top-1.5 -right-1.5 cursor-nesw-resize'
                              : corner === 'sw'
                              ? '-bottom-1.5 -left-1.5 cursor-nesw-resize'
                              : '-bottom-1.5 -right-1.5 cursor-nwse-resize';
                          return (
                            <div
                              key={corner}
                              data-mapping-badge="true"
                              onPointerDown={(e) => handleBoxPointerDown(e, m, corner)}
                              className={`absolute w-3 h-3 rounded-full bg-indigo-600 border-2 border-white shadow ${posCls}`}
                            />
                          );
                        })}
                    </div>
                  );
                })}

                {/* Drag-to-Draw Box */}
                {interaction?.mode === 'draw' && (
                  <div
                    style={{
                      left: `${Math.min(interaction.startX, interaction.currX) * 100}%`,
                      top: `${Math.min(interaction.startY, interaction.currY) * 100}%`,
                      width: `${Math.abs(interaction.currX - interaction.startX) * 100}%`,
                      height: `${Math.abs(interaction.currY - interaction.startY) * 100}%`,
                    }}
                    className={`absolute border-2 border-dashed pointer-events-none z-40 ${
                      activeTool === 'image'
                        ? 'bg-amber-400/25 border-amber-600'
                        : 'bg-blue-400/25 border-blue-600'
                    }`}
                  />
                )}
              </PdfPageCanvas>
            </div>
          </div>
        </div>

        {/* Slim Contextual Sidebar */}
        <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-200 p-4 shadow-sm space-y-4">
          {selectedMapping ? (
            <div className="space-y-3.5">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <span className="text-xs font-bold text-slate-900">Edit Box</span>
                <button
                  type="button"
                  onClick={() => setSelectedUid(null)}
                  className="text-xs font-semibold text-slate-500 hover:text-slate-900 cursor-pointer"
                >
                  Done
                </button>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Label</label>
                <input
                  type="text"
                  value={selectedMapping.label || ''}
                  onChange={(e) => handleLabelChange(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Type</label>
                <select
                  value={selectedMapping.type}
                  onChange={(e) => handleUpdateSelected({ type: e.target.value })}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-slate-900"
                >
                  <option value="text">Text</option>
                  <option value="multiline">Multiline</option>
                  <option value="checkbox">Checkbox</option>
                  <option value="image">Photo / Signature</option>
                </select>
              </div>

              {selectedMapping.type === 'checkbox' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Option
                  </label>
                  <input
                    type="text"
                    value={selectedMapping.match_value || ''}
                    onChange={(e) => handleUpdateSelected({ match_value: e.target.value })}
                    placeholder="e.g. Yes, Male, Full-Time"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-slate-900"
                  />
                </div>
              )}

              {/* Collapsible Advanced Controls */}
              <div className="pt-1 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  className="w-full flex items-center justify-between text-xs font-semibold text-slate-600 hover:text-slate-900 py-1 cursor-pointer"
                >
                  <span>Advanced</span>
                  {showAdvanced ? (
                    <ChevronUp className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5" />
                  )}
                </button>

                {showAdvanced && (
                  <div className="mt-2.5 space-y-2.5">
                    {selectedMapping.type !== 'image' && selectedMapping.type !== 'checkbox' && (
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                            Font size
                          </label>
                          <input
                            type="number"
                            min={6}
                            max={22}
                            step={0.5}
                            value={selectedMapping.font_size ?? 10}
                            onChange={(e) =>
                              handleUpdateSelected({ font_size: Number(e.target.value) })
                            }
                            className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                            Align
                          </label>
                          <select
                            value={selectedMapping.align || 'left'}
                            onChange={(e) => handleUpdateSelected({ align: e.target.value })}
                            className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs"
                          >
                            <option value="left">Left</option>
                            <option value="center">Center</option>
                            <option value="right">Right</option>
                          </select>
                        </div>
                      </div>
                    )}

                    <div>
                      <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                        Field key
                      </label>
                      <input
                        type="text"
                        value={selectedMapping.field_key || ''}
                        onChange={(e) => {
                          setCustomKeyEdited(true);
                          handleUpdateSelected({ field_key: slugifyLabel(e.target.value) });
                        }}
                        className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                        Question text
                      </label>
                      <input
                        type="text"
                        value={selectedMapping.question_text || ''}
                        onChange={(e) =>
                          handleUpdateSelected({ question_text: e.target.value })
                        }
                        className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs"
                      />
                    </div>
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={() => handleRemoveMapping(selectedMapping._uid)}
                className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-red-50 hover:bg-red-100 text-red-700 font-semibold text-xs py-2 transition cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Remove Box
              </button>
            </div>
          ) : (
            <div className="space-y-3.5">
              <p className="text-xs text-slate-500 leading-relaxed bg-slate-50 rounded-xl p-3 border border-slate-100">
                Drag on the PDF to add a box, or click any box to move, resize, or edit.
              </p>

              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                  Page {pageNumber} ({pageMappings.length})
                </h3>
                <div className="max-h-80 overflow-y-auto space-y-1.5 pr-1">
                  {pageMappings.length === 0 ? (
                    <p className="text-xs text-slate-400 py-3 text-center">
                      No boxes on this page.
                    </p>
                  ) : (
                    pageMappings.map((m) => {
                      const displayLbl = m.label || humanizeFieldKey(m.field_key);
                      return (
                        <div
                          key={m._uid}
                          onClick={() => setSelectedUid(m._uid)}
                          className="group flex items-center justify-between text-xs bg-slate-50 hover:bg-slate-100 rounded-xl px-2.5 py-2 border border-slate-200/70 cursor-pointer transition"
                        >
                          <span className="font-medium text-slate-800 truncate pr-2">
                            {displayLbl}
                            {m.match_value ? ` (${m.match_value})` : ''}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveMapping(m._uid);
                            }}
                            className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-600 p-0.5 cursor-pointer transition"
                            title="Remove box"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="pt-3 border-t border-slate-100">
            <label className="inline-flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showQALinks}
                onChange={(e) => setShowQALinks(e.target.checked)}
                className="rounded accent-slate-900"
              />
              Show question→answer links
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}

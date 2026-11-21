import React, { useEffect, useRef, useState } from 'react';
import {
  Users,
  MoreHorizontal,
  Wand2,
  ScanSearch,
  FileSearch,
  Sliders,
  Trash2,
  AlertTriangle,
} from 'lucide-react';

export default function DocumentPickerCard({
  activeTemplate,
  docSpec,
  reanalyzing,
  onOpenProfiles,
  onLoadDemo,
  onReanalyze,
  onViewScraped,
  onOpenMapper,
  onDeleteTemplate,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDocClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [menuOpen]);

  if (!activeTemplate) return null;

  const warnings = activeTemplate.analysis_summary?.warnings || [];
  const totalFields =
    (docSpec.nonImageFields?.length || 0) + (docSpec.imageFields?.length || 0);

  const handleDeleteClick = async () => {
    setMenuOpen(false);
    if (!onDeleteTemplate) return;
    const confirmed = window.confirm(
      `Delete "${activeTemplate.name}" and remove its PDF file?`
    );
    if (!confirmed) return;
    setDeleting(true);
    try {
      await onDeleteTemplate(activeTemplate.id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200/90 shadow-xs px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
      {/* Left: Title + Subtle Metadata + Concise Warning */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0">
        <h1 className="text-sm font-bold text-slate-900 truncate max-w-md">
          {activeTemplate.name}
        </h1>
        <span className="text-xs text-slate-500">
          {activeTemplate.page_count} {activeTemplate.page_count === 1 ? 'page' : 'pages'} •{' '}
          {totalFields} {totalFields === 1 ? 'field' : 'fields'}
        </span>
        {warnings.length > 0 && (
          <span
            className="inline-flex items-center gap-1 text-[11px] font-medium bg-amber-50 text-amber-900 border border-amber-200 px-2.5 py-0.5 rounded-full"
            title={warnings.join(' ')}
          >
            <AlertTriangle className="w-3 h-3 text-amber-600 shrink-0" />
            <span className="truncate max-w-xs sm:max-w-md">{warnings[0]}</span>
          </span>
        )}
      </div>

      {/* Right: Profiles + Compact More Menu */}
      <div className="flex items-center gap-2 shrink-0">
        <button
          type="button"
          onClick={onOpenProfiles}
          data-testid="open-profiles-btn"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded-xl transition cursor-pointer"
        >
          <Users className="w-3.5 h-3.5 text-indigo-600" />
          Profiles
        </button>

        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            data-testid="doc-more-menu-btn"
            aria-label="More document options"
            className="inline-flex items-center justify-center w-8 h-8 rounded-xl border border-slate-200 bg-white hover:bg-slate-100 text-slate-700 transition cursor-pointer"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 mt-1.5 w-56 rounded-2xl bg-white border border-slate-200 shadow-xl py-1.5 z-50 text-xs">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  onLoadDemo();
                }}
                data-testid="load-sample-dictionary-btn"
                className="w-full px-3.5 py-2 text-left flex items-center gap-2.5 text-slate-700 hover:bg-slate-50 cursor-pointer"
              >
                <Wand2 className="w-3.5 h-3.5 text-amber-600" />
                Load Sample Answers &amp; Media
              </button>
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => {
                  setMenuOpen(false);
                  onReanalyze();
                }}
                className="w-full px-3.5 py-2 text-left flex items-center gap-2.5 text-slate-700 hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
              >
                <ScanSearch className="w-3.5 h-3.5 text-emerald-600" />
                {reanalyzing ? 'Scanning PDF...' : 'Re-scan PDF for Fields'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  if (onViewScraped) onViewScraped();
                }}
                data-testid="view-scraped-content-btn"
                className="w-full px-3.5 py-2 text-left flex items-center gap-2.5 text-slate-700 hover:bg-slate-50 cursor-pointer"
              >
                <FileSearch className="w-3.5 h-3.5 text-indigo-600" />
                View Scraped PDF Text
              </button>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  onOpenMapper();
                }}
                className="w-full px-3.5 py-2 text-left flex items-center gap-2.5 text-slate-700 hover:bg-slate-50 cursor-pointer"
              >
                <Sliders className="w-3.5 h-3.5 text-slate-600" />
                Adjust Box Positions
              </button>

              <div className="my-1 border-t border-slate-100" />

              <button
                type="button"
                disabled={deleting}
                onClick={handleDeleteClick}
                data-testid="delete-template-btn"
                className="w-full px-3.5 py-2 text-left flex items-center gap-2.5 text-red-600 hover:bg-red-50 disabled:opacity-50 cursor-pointer font-medium"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Delete Document
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

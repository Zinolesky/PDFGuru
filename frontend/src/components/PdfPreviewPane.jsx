import React, { useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Share2,
  Eye,
  EyeOff,
  Sliders,
  RotateCcw,
} from 'lucide-react';
import PdfPageCanvas from './PdfPageCanvas';
import { humanizeFieldKey } from '../constants';

export default function PdfPreviewPane({
  activeTemplate,
  generatedPdfUrl,
  previewPage,
  totalTemplatePages,
  mappedPages,
  onPreviewPageChange,
  onResetPreview,
  onDownloadPdf,
  onSharePdf,
  onOpenMapper,
}) {
  const [showBoxes, setShowBoxes] = useState(true);

  const pageMappings = (activeTemplate?.mappings || []).filter(
    (m) => (m.page_number || 1) === previewPage
  );

  return (
    <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-4 space-y-3.5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900">
            {generatedPdfUrl ? 'Filled PDF Ready' : 'Preview'}
          </h2>
          {generatedPdfUrl && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              Stamped
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {generatedPdfUrl ? (
            <button
              type="button"
              onClick={onResetPreview}
              className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-900 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Back to blank
            </button>
          ) : activeTemplate ? (
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

      {/* Download & Share Bar when Stamped */}
      {generatedPdfUrl && (
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
      {generatedPdfUrl ? (
        <div data-testid="stamped-pdf-preview">
          <PdfPageCanvas pdfUrl={generatedPdfUrl} pageNumber={previewPage} />
        </div>
      ) : activeTemplate ? (
        <div data-testid="blank-template-preview">
          <PdfPageCanvas
            pdfUrl={`/api/templates/${activeTemplate.id}/pdf`}
            fallbackImageUrl={`/api/templates/${activeTemplate.id}/page-image/${previewPage}`}
            pageNumber={previewPage}
          >
            {showBoxes &&
              pageMappings.map((m, idx) => {
                const lbl = m.label || humanizeFieldKey(m.field_key);
                if (m.type === 'checkbox') {
                  return (
                    <div
                      key={m.id || idx}
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
                    key={m.id || idx}
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

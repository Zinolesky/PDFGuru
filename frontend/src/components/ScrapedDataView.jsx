import React, { useEffect, useMemo, useState } from 'react';
import {
  Copy,
  Check,
  Download,
  FileText,
  Table as TableIcon,
  ListTree,
  Sliders,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

const PAGE_TYPE_LABELS = {
  acroform: 'Interactive PDF',
  digital_flat: 'Form Page',
  scanned_image: 'Scanned Page',
  prose: 'Document Page',
};

export default function ScrapedDataView({ activeTemplate, onOpenMapper }) {
  const [scrapedData, setScrapedData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedPage, setSelectedPage] = useState('all');
  const [copiedAll, setCopiedAll] = useState(false);
  const [rawOpenPages, setRawOpenPages] = useState({});

  useEffect(() => {
    let cancelled = false;
    if (!activeTemplate?.id) {
      setScrapedData(null);
      return undefined;
    }
    setLoading(true);
    setSelectedPage('all');
    setRawOpenPages({});
    (async () => {
      try {
        const res = await fetch(`/api/templates/${activeTemplate.id}/scraped-content`);
        if (res.ok && !cancelled) {
          setScrapedData(await res.json());
        }
      } catch {
        if (!cancelled) setScrapedData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTemplate]);

  const pages = scrapedData?.pages || [];

  const visiblePages = useMemo(() => {
    if (selectedPage === 'all') return pages;
    return pages.filter((p) => p.page_number === Number(selectedPage));
  }, [pages, selectedPage]);

  const handleCopyAllText = async () => {
    const combined = pages
      .map((p) => (pages.length > 1 ? `--- Page ${p.page_number} ---\n${p.full_text || ''}` : p.full_text || ''))
      .join('\n\n')
      .trim();
    if (!combined) return;
    try {
      await navigator.clipboard.writeText(combined);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleExportJson = () => {
    if (!scrapedData) return;
    const payload = {
      document_name: scrapedData.document_name,
      page_count: scrapedData.page_count,
      analysis_method: scrapedData.analysis_method,
      pages: scrapedData.pages,
      detected_fields: activeTemplate?.mappings || [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const safeName = (scrapedData.document_name || 'document')
      .trim()
      .replace(/[^a-zA-Z0-9]+/g, '_');
    a.href = url;
    a.download = `${safeName}_scraped.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!activeTemplate) return null;

  if (loading) {
    return (
      <div className="py-12 text-center text-xs text-slate-500">
        Loading scraped PDF data...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopyAllText}
            disabled={pages.length === 0}
            data-testid="copy-scraped-text-btn"
            className="inline-flex items-center gap-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-xl transition cursor-pointer disabled:opacity-40"
          >
            {copiedAll ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                Copied!
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                Copy All Text
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleExportJson}
            disabled={!scrapedData}
            data-testid="export-scraped-json-btn"
            className="inline-flex items-center gap-1.5 text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-800 px-3 py-1.5 rounded-xl transition cursor-pointer disabled:opacity-40"
          >
            <Download className="w-3.5 h-3.5" />
            Export JSON
          </button>
        </div>

        {pages.length > 1 && (
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => setSelectedPage('all')}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold cursor-pointer transition ${
                selectedPage === 'all'
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              All Pages
            </button>
            {pages.map((p) => (
              <button
                key={p.page_number}
                type="button"
                onClick={() => setSelectedPage(String(p.page_number))}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold cursor-pointer transition ${
                  Number(selectedPage) === p.page_number
                    ? 'bg-slate-900 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                P.{p.page_number}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Per-Page Structured Content Cards */}
      {visiblePages.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          No scraped text cached yet. Choose <strong>Re-scan PDF for Fields</strong> from the{' '}
          <strong>•••</strong> menu to inspect this PDF.
        </div>
      ) : (
        <div className="space-y-4">
          {visiblePages.map((pg) => {
            const kvs = pg.key_values || [];
            const tables = pg.tables || [];
            const structSections = pg.structured_sections || [];
            const hasStructured = kvs.length > 0 || tables.length > 0 || structSections.length > 0;
            const isRawOpen = rawOpenPages[pg.page_number] ?? !hasStructured;
            const friendlyType = PAGE_TYPE_LABELS[pg.page_type] || 'Document Page';

            return (
              <div
                key={pg.page_number}
                data-testid={`scraped-page-${pg.page_number}`}
                className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4 space-y-4"
              >
                {/* Page Header & Vision Summary */}
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-bold text-slate-900">
                      Page {pg.page_number}
                    </span>
                    <span className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-white border border-slate-200 text-slate-600">
                      {friendlyType}
                    </span>
                  </div>
                  {pg.page_summary && (
                    <p className="text-xs text-slate-600 leading-relaxed">{pg.page_summary}</p>
                  )}
                </div>

                {/* Extracted Key-Value Data */}
                {kvs.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <ListTree className="w-3.5 h-3.5 text-indigo-600" />
                      Extracted Key-Value Data
                    </h4>
                    <div className="rounded-xl border border-slate-200 bg-white divide-y divide-slate-100 overflow-hidden">
                      {kvs.map((kv, idx) => (
                        <div
                          key={idx}
                          className="grid grid-cols-1 sm:grid-cols-12 gap-1 sm:gap-3 px-3 py-2 text-xs"
                        >
                          <span className="sm:col-span-4 font-semibold text-slate-600 break-words">
                            {kv.key}
                          </span>
                          <span className="sm:col-span-8 text-slate-900 break-words">
                            {kv.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Extracted Tables */}
                {tables.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <TableIcon className="w-3.5 h-3.5 text-emerald-600" />
                      Extracted Tables ({tables.length})
                    </h4>
                    <div className="space-y-2.5">
                      {tables.map((tbl, tIdx) => (
                        <div
                          key={tIdx}
                          className="overflow-x-auto rounded-xl border border-slate-200 bg-white"
                        >
                          <table className="w-full text-left border-collapse text-xs">
                            <tbody>
                              {tbl.map((row, rIdx) => (
                                <tr
                                  key={rIdx}
                                  className="border-b border-slate-100 last:border-b-0"
                                >
                                  {row.map((cell, cIdx) => (
                                    <td
                                      key={cIdx}
                                      className={`px-3 py-2 align-top border-r border-slate-100 last:border-r-0 ${
                                        cIdx === 0 ? 'font-medium text-slate-700 bg-slate-50/60' : 'text-slate-900'
                                      }`}
                                    >
                                      {cell || <span className="text-slate-300">—</span>}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Structured Document Sections */}
                {structSections.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5 text-slate-600" />
                      Document Sections &amp; Content
                    </h4>
                    <div className="space-y-2">
                      {structSections.map((sec, sIdx) => (
                        <div
                          key={sIdx}
                          className="rounded-xl border border-slate-200 bg-white p-3 space-y-1.5"
                        >
                          <div className="text-xs font-bold text-slate-800">{sec.title}</div>
                          {sec.lines?.length > 0 && (
                            <div className="text-xs text-slate-600 space-y-1 leading-relaxed">
                              {sec.lines.map((line, lIdx) => (
                                <p key={lIdx} className="break-words">
                                  {line}
                                </p>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Raw Text Toggle */}
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() =>
                      setRawOpenPages((prev) => ({
                        ...prev,
                        [pg.page_number]: !isRawOpen,
                      }))
                    }
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-slate-900 cursor-pointer"
                  >
                    {isRawOpen ? (
                      <ChevronUp className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5" />
                    )}
                    {isRawOpen ? 'Hide Raw Text' : 'View Raw Text'}
                  </button>

                  {isRawOpen && (
                    <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] bg-white border border-slate-200 rounded-xl p-3 max-h-64 overflow-y-auto text-slate-800 leading-relaxed">
                      {pg.full_text || '(No selectable text detected on this page)'}
                    </pre>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Callout when PDF has 0 detected fields (read-only PDF) */}
      {(activeTemplate.mappings?.length || 0) === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3.5 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-600">
            This PDF looks like a read-only document. Want to write text or sign on top of it?
          </p>
          {onOpenMapper && (
            <button
              type="button"
              onClick={onOpenMapper}
              className="inline-flex items-center gap-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-xl transition cursor-pointer shrink-0"
            >
              <Sliders className="w-3.5 h-3.5 text-amber-400" />
              Adjust Boxes
            </button>
          )}
        </div>
      )}
    </div>
  );
}

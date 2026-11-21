import React from 'react';
import {
  Copy,
  Check,
  Share2,
  Sparkles,
  AlertTriangle,
} from 'lucide-react';

export default function DictionaryWorkbench({
  dictionaryText,
  includeOptionHints,
  copiedBlank,
  parsing,
  parserInfo,
  onDictionaryTextChange,
  onToggleOptionHints,
  onResetBlank,
  onCopyBlankFormat,
  onShareFormat,
  onParseDictionary,
}) {
  return (
    <div className="space-y-3.5">
      <p className="text-xs text-slate-600 leading-relaxed">
        Copy the blank questions to send to someone, or paste their reply / any notes below to auto-fill the form.
      </p>

      {/* Clean Action Row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCopyBlankFormat}
            data-testid="copy-blank-dictionary-btn"
            className="inline-flex items-center gap-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-xl transition cursor-pointer"
          >
            {copiedBlank ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                Copied!
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                Copy Blank Questions
              </>
            )}
          </button>

          <button
            type="button"
            onClick={onShareFormat}
            data-testid="share-dictionary-format-btn"
            className="inline-flex items-center gap-1.5 text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-800 px-3 py-1.5 rounded-xl transition cursor-pointer"
          >
            <Share2 className="w-3.5 h-3.5" />
            Share
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <label className="inline-flex items-center gap-1.5 text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={includeOptionHints}
              onChange={(e) => onToggleOptionHints(e.target.checked)}
              className="rounded accent-slate-900"
            />
            Show choice hints
          </label>
          <button
            type="button"
            onClick={onResetBlank}
            className="font-semibold text-slate-500 hover:text-slate-900 underline cursor-pointer"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Textarea */}
      <textarea
        data-testid="dictionary-textarea"
        rows={10}
        value={dictionaryText}
        onChange={(e) => onDictionaryTextChange(e.target.value)}
        placeholder={'First name: \nLast name: \nEmail address: \nPhone number: '}
        className="w-full rounded-xl border border-slate-300 bg-slate-50/70 p-3.5 text-xs font-mono text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-900 leading-relaxed"
      />

      {parserInfo?.warning && (
        <div className="flex items-center gap-2 text-xs text-amber-900 bg-amber-50 border border-amber-200 px-3 py-2 rounded-xl">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0" />
          <span>{parserInfo.warning}</span>
        </div>
      )}

      <button
        type="button"
        onClick={onParseDictionary}
        disabled={parsing}
        data-testid="parse-dictionary-btn"
        className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm py-3 px-4 shadow-sm transition cursor-pointer disabled:opacity-50"
      >
        <Sparkles className="w-4 h-4 text-amber-400" />
        {parsing ? 'Auto-Filling Form...' : 'Auto-Fill Form'}
      </button>
    </div>
  );
}

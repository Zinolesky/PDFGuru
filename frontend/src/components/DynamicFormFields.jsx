import React, { useMemo } from 'react';
import { Sliders } from 'lucide-react';
import { CHECKBOX_FIELD_OPTIONS } from '../constants';

const OPTION_CLUTTER_REGEX =
  /^(?:(?:yes|no|none|ongoing|completed|exempted|full[\s-]*time|part[\s-]*time|freelance|not\s+employed|male|female|other)\s*[([][\s_]*[)\]]\s*)+/i;

function cleanPromptText(raw) {
  let s = String(raw || '')
    .replace(OPTION_CLUTTER_REGEX, '')
    .replace(/\s+/g, ' ')
    .trim();
  // Remove trailing colons while preserving question marks
  if (s.endsWith(':')) {
    s = s.slice(0, -1).trim();
  }
  return s;
}

function extractWords(str) {
  return String(str || '')
    .toLowerCase()
    .match(/[a-z0-9]+/g) || [];
}

function formatFieldPrompt(field) {
  const rawQ = cleanPromptText(field.question_text);
  const rawL = cleanPromptText(field.label);
  const primary = rawQ || rawL || 'Field';

  const splitIdx = primary.lastIndexOf(' — ');
  if (splitIdx > 0) {
    const parentPart = cleanPromptText(primary.slice(0, splitIdx));
    const followupPart = cleanPromptText(primary.slice(splitIdx + 3));
    return {
      mainQuestion: parentPart || rawL || primary,
      followupTag: followupPart || null,
    };
  }

  let mainQuestion = primary;
  if (rawQ && rawL && rawL.toLowerCase() !== rawQ.toLowerCase()) {
    const qWords = extractWords(rawQ);
    const qSet = new Set(qWords);
    const lWords = extractWords(rawL);
    const extraWords = lWords.filter((w) => !qSet.has(w));
    const overlapCount = lWords.filter((w) => qSet.has(w)).length;

    if (extraWords.length > 0) {
      if (rawL.toLowerCase().startsWith(rawQ.toLowerCase())) {
        const suffix = rawL
          .slice(rawQ.length)
          .replace(/^[\s:\-–—(]+|[)\s]+$/g, '')
          .trim();
        mainQuestion = suffix ? `${rawQ} (${suffix})` : rawL;
      } else if (
        rawL.length > rawQ.length &&
        qWords.length > 0 &&
        overlapCount >= Math.ceil(qWords.length * 0.6)
      ) {
        mainQuestion = rawL;
      }
    }
  }

  return {
    mainQuestion,
    followupTag: null,
  };
}

function buildSectionDisambiguator(field, mainQuestion) {
  const mainLower = mainQuestion.toLowerCase();
  const mainWords = new Set(extractWords(mainLower));
  const rawL = cleanPromptText(field.label);
  if (rawL && rawL.toLowerCase() !== mainLower) {
    const extra = extractWords(rawL).filter((w) => !mainWords.has(w));
    if (extra.length > 0 && rawL.length <= 42) {
      return rawL;
    }
  }
  const fkHuman = String(field.field_key || '')
    .replace(/_/g, ' ')
    .trim();
  const fkExtra = extractWords(fkHuman).filter((w) => !mainWords.has(w));
  if (fkExtra.length > 0) {
    return fkExtra.join(' ');
  }
  return null;
}

function getNeutralPlaceholder(field, followupTag) {
  const k = String(field.field_key || '').toLowerCase();
  const q = String(`${field.question_text || ''} ${field.label || ''}`).toLowerCase();
  const combined = `${k} ${q}`;
  if (
    /\bword(?:s)?\b/.test(combined) &&
    /\b(?:amount|cost|sum|total|price|fee)\b/.test(combined)
  ) {
    return 'Enter amount in words...';
  }
  if (/\bfigure(?:s)?\b/.test(combined)) {
    return 'Enter amount in figures...';
  }
  if (k.includes('date') || k.includes('dob') || /\bdate\b/.test(q)) {
    return 'Enter date...';
  }
  if (followupTag) {
    return 'Enter details...';
  }
  if (field.type === 'multiline') {
    return 'Write your response...';
  }
  return 'Type your answer...';
}

export default function DynamicFormFields({
  docSpec,
  formData,
  onFieldChange,
  onOpenMapper,
}) {
  const groupedSections = useMemo(() => {
    const fields = docSpec.nonImageFields || [];
    const map = new Map();
    fields.forEach((f) => {
      const sec = f.section || 'Document Fields';
      if (!map.has(sec)) {
        map.set(sec, []);
      }
      map.get(sec).push(f);
    });
    return Array.from(map.entries());
  }, [docSpec.nonImageFields]);

  const showPageBadges = useMemo(() => {
    const pageSet = new Set();
    (docSpec.nonImageFields || []).forEach((f) => {
      (f.page_numbers || [1]).forEach((p) => pageSet.add(p));
    });
    return pageSet.size > 1;
  }, [docSpec.nonImageFields]);

  if (!docSpec.nonImageFields?.length) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 p-8 text-center space-y-3">
        <p className="text-sm font-medium text-slate-600">
          No text or checkbox fields were detected on this PDF yet.
        </p>
        {onOpenMapper && (
          <button
            type="button"
            onClick={onOpenMapper}
            className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold px-4 py-2 transition cursor-pointer"
          >
            <Sliders className="w-3.5 h-3.5 text-amber-400" />
            Adjust Boxes
          </button>
        )}
      </div>
    );
  }

  const showSectionHeaders = groupedSections.length > 1;
  let runningQuestionNum = 0;

  return (
    <div className="space-y-6">
      {groupedSections.map(([sectionName, sectionFields]) => (
        <div key={sectionName} className="space-y-3.5">
          {showSectionHeaders && (
            <div className="border-b border-slate-100 pb-1.5">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                {sectionName}
              </h3>
            </div>
          )}

          {/* Render fields strictly in PDF reading order so follow-ups stay right under their question */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {(() => {
              const formattedItems = sectionFields.map((field) => ({
                field,
                ...formatFieldPrompt(field),
              }));
              const promptCounts = new Map();
              formattedItems.forEach(({ mainQuestion, followupTag }) => {
                const key = `${mainQuestion.toLowerCase()}||${(followupTag || '').toLowerCase()}`;
                promptCounts.set(key, (promptCounts.get(key) || 0) + 1);
              });

              return formattedItems.map(({ field, mainQuestion: baseQuestion, followupTag }) => {
                runningQuestionNum += 1;
                const qNum = runningQuestionNum;
                const dupKey = `${baseQuestion.toLowerCase()}||${(followupTag || '').toLowerCase()}`;
                const qualifier =
                  (promptCounts.get(dupKey) || 0) > 1
                    ? buildSectionDisambiguator(field, baseQuestion)
                    : null;
                const mainQuestion = qualifier ? `${baseQuestion} (${qualifier})` : baseQuestion;
                const isMultiline = field.type === 'multiline';
                const isCheckbox = field.type === 'checkbox';
                const isWide =
                  isMultiline ||
                  Boolean(followupTag) ||
                  mainQuestion.length > 34 ||
                  field.field_key.includes('address') ||
                  field.field_key.includes('notes') ||
                  field.field_key.includes('comment') ||
                  field.field_key === 'full_name';

                const opts = isCheckbox
                  ? field.options?.length > 0
                    ? field.options
                    : CHECKBOX_FIELD_OPTIONS[field.field_key]?.values || ['Yes', 'No']
                  : [];

                const placeholder = getNeutralPlaceholder(field, followupTag);
                const pageBadge =
                  showPageBadges && field.page_numbers?.length
                    ? `P.${field.page_numbers[0]}`
                    : null;

                return (
                  <div
                    key={field.field_key}
                    className={`${isWide ? 'sm:col-span-2' : ''} ${
                      followupTag
                        ? 'rounded-xl border border-amber-200/80 bg-amber-50/35 px-3 py-2.5'
                        : ''
                    }`}
                  >
                    <label className="block text-xs font-semibold text-slate-800 mb-1.5 leading-snug">
                      <span className="text-slate-400 font-bold mr-1.5">{qNum}.</span>
                      <span>{mainQuestion}</span>
                      {followupTag && (
                        <span className="inline-flex items-center ml-2 px-2 py-0.5 rounded-md bg-amber-100 text-amber-900 text-[11px] font-bold align-middle">
                          Follow-up: {followupTag}
                        </span>
                      )}
                      {pageBadge && (
                        <span className="inline-flex items-center ml-1.5 px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 text-[10px] font-semibold align-middle">
                          {pageBadge}
                        </span>
                      )}
                    </label>

                    {isCheckbox ? (
                      <select
                        data-testid={`field-${field.field_key}`}
                        value={formData[field.field_key] || ''}
                        onChange={(e) => onFieldChange(field.field_key, e.target.value)}
                        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
                      >
                        <option value="">Select...</option>
                        {opts.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    ) : isMultiline ? (
                      <textarea
                        rows={3}
                        data-testid={`field-${field.field_key}`}
                        value={formData[field.field_key] || ''}
                        onChange={(e) => onFieldChange(field.field_key, e.target.value)}
                        placeholder={placeholder}
                        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
                      />
                    ) : (
                      <input
                        type="text"
                        data-testid={`field-${field.field_key}`}
                        value={formData[field.field_key] || ''}
                        onChange={(e) => onFieldChange(field.field_key, e.target.value)}
                        placeholder={placeholder}
                        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
                      />
                    )}
                  </div>
                );
              });
            })()}
          </div>
        </div>
      ))}
    </div>
  );
}

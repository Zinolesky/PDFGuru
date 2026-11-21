import React, { useMemo } from 'react';
import { Sliders } from 'lucide-react';
import { CHECKBOX_FIELD_OPTIONS } from '../constants';

function hasMeaningfulQuestionHint(questionText, label) {
  if (!questionText) return false;
  const cleanQ = questionText
    .trim()
    .toLowerCase()
    .replace(/[\s:?\-._]+$/g, '')
    .replace(/\s+/g, ' ');
  const cleanL = (label || '')
    .trim()
    .toLowerCase()
    .replace(/[\s:?\-._]+$/g, '')
    .replace(/\s+/g, ' ');
  if (!cleanQ || cleanQ === cleanL) return false;
  // Avoid redundant hints that only differ slightly (e.g. "first name" vs "first name")
  return cleanQ.length > cleanL.length + 3 || !cleanQ.includes(cleanL);
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

  return (
    <div className="space-y-6">
      {groupedSections.map(([sectionName, sectionFields]) => {
        const checkboxes = sectionFields.filter((f) => f.type === 'checkbox');
        const texts = sectionFields.filter((f) => f.type !== 'checkbox');

        return (
          <div key={sectionName} className="space-y-3.5">
            {showSectionHeaders && (
              <div className="border-b border-slate-100 pb-1.5">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  {sectionName}
                </h3>
              </div>
            )}

            {checkboxes.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {checkboxes.map((field) => {
                  const opts =
                    field.options?.length > 0
                      ? field.options
                      : CHECKBOX_FIELD_OPTIONS[field.field_key]?.values || ['Yes', 'No'];
                  const showHint = hasMeaningfulQuestionHint(field.question_text, field.label);

                  return (
                    <div key={field.field_key}>
                      <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                        {field.label}
                      </label>
                      {showHint && (
                        <p className="text-[11px] text-slate-500 mb-1.5 leading-snug">
                          {field.question_text}
                        </p>
                      )}
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
                    </div>
                  );
                })}
              </div>
            )}

            {texts.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {texts.map((field) => {
                  const isMultiline = field.type === 'multiline';
                  const isWide =
                    isMultiline ||
                    field.field_key.includes('address') ||
                    field.field_key.includes('notes') ||
                    field.field_key.includes('comment') ||
                    field.field_key === 'full_name';
                  const showHint = hasMeaningfulQuestionHint(field.question_text, field.label);

                  return (
                    <div key={field.field_key} className={isWide ? 'sm:col-span-2' : ''}>
                      <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                        {field.label}
                      </label>
                      {showHint && (
                        <p className="text-[11px] text-slate-500 mb-1.5 leading-snug">
                          {field.question_text}
                        </p>
                      )}
                      {isMultiline ? (
                        <textarea
                          rows={3}
                          data-testid={`field-${field.field_key}`}
                          value={formData[field.field_key] || ''}
                          onChange={(e) => onFieldChange(field.field_key, e.target.value)}
                          placeholder={field.label}
                          className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
                        />
                      ) : (
                        <input
                          type="text"
                          data-testid={`field-${field.field_key}`}
                          value={formData[field.field_key] || ''}
                          onChange={(e) => onFieldChange(field.field_key, e.target.value)}
                          placeholder={field.label}
                          className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

import React, { useEffect, useRef, useState } from 'react';
import {
  Camera,
  PenTool,
  Crop,
  RotateCw,
  Trash2,
  SlidersHorizontal,
  Sliders,
} from 'lucide-react';
import { isSignatureLikeKey } from '../constants';

const CHECKERBOARD_BG = {
  backgroundImage:
    'linear-gradient(45deg, #f1f5f9 25%, transparent 25%), linear-gradient(-45deg, #f1f5f9 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #f1f5f9 75%), linear-gradient(-45deg, transparent 75%, #f1f5f9 75%)',
  backgroundSize: '12px 12px',
  backgroundPosition: '0 0, 0 6px, 6px -6px, -6px 0',
};

function MediaSlotCard({
  slot,
  state,
  isPasteTarget,
  showPasteHighlight,
  onSelectPasteTarget,
  onFileChange,
  onUpdateState,
  onClear,
}) {
  const [showTune, setShowTune] = useState(false);
  const mode = state?.mode || (isSignatureLikeKey(slot.field_key) ? 'signature' : 'photo');
  const isSig = mode === 'signature';
  const rotateDeg = state?.rotateDeg || 0;
  const threshold = state?.threshold ?? 205;
  const smartCrop = state?.smartCrop ?? true;
  const previewUrl = state?.previewUrl || null;
  const file = state?.file || null;

  // Debounced + AbortController preview processing
  const abortRef = useRef(null);
  useEffect(() => {
    if (!file) {
      setShowTune(false);
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        onUpdateState(slot.field_key, { previewUrl: null });
      }
      return undefined;
    }

    const timer = setTimeout(async () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const fd = new FormData();
        fd.append('image', file);
        fd.append('mode', mode);
        fd.append('threshold', String(threshold));
        fd.append('rotate_deg', String(rotateDeg));
        fd.append('smart_crop', String(smartCrop));

        const res = await fetch('/api/process-image-preview', {
          method: 'POST',
          body: fd,
          signal: controller.signal,
        });
        if (res.ok) {
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          onUpdateState(slot.field_key, { previewUrl: url }, true);
          return;
        }
      } catch (err) {
        if (err.name === 'AbortError') return;
      }

      const fallbackUrl = URL.createObjectURL(file);
      onUpdateState(slot.field_key, { previewUrl: fallbackUrl }, true);
    }, 260);

    return () => {
      clearTimeout(timer);
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [file, mode, rotateDeg, threshold, smartCrop, slot.field_key]);

  return (
    <div
      data-image-dropzone="true"
      onClick={() => onSelectPasteTarget(slot.field_key)}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        const dropped = e.dataTransfer?.files?.[0];
        if (dropped && dropped.type.startsWith('image/')) {
          onFileChange(slot.field_key, dropped);
        }
      }}
      className={`rounded-xl border p-3 transition flex flex-col justify-between bg-white ${
        showPasteHighlight && isPasteTarget
          ? 'border-slate-900 ring-2 ring-slate-900/10'
          : 'border-slate-200 hover:border-slate-300'
      }`}
    >
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          {isSig ? (
            <PenTool className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
          ) : (
            <Camera className="w-3.5 h-3.5 text-amber-600 shrink-0" />
          )}
          <span className="text-xs font-semibold text-slate-800 truncate">{slot.label}</span>
        </div>

        <label
          style={isSig && previewUrl ? CHECKERBOARD_BG : undefined}
          className="relative flex flex-col items-center justify-center h-24 rounded-lg border border-dashed border-slate-300 hover:border-slate-500 bg-slate-50 cursor-pointer overflow-hidden p-2 transition"
        >
          {previewUrl ? (
            <img
              src={previewUrl}
              alt={`${slot.label} preview`}
              data-testid={`media-preview-${slot.field_key}`}
              className="max-h-full max-w-full object-contain rounded"
            />
          ) : (
            <div className="text-center">
              <div className="text-xs font-medium text-slate-600">
                Click, drop, or Ctrl+V
              </div>
            </div>
          )}
          <input
            type="file"
            accept="image/*"
            data-testid={`media-input-${slot.field_key}`}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFileChange(slot.field_key, f);
              e.target.value = '';
            }}
            className="hidden"
          />
        </label>
      </div>

      {/* Controls only appear AFTER an image is uploaded */}
      {file && (
        <div className="mt-2.5 pt-2 border-t border-slate-100 space-y-2">
          <div className="flex items-center justify-between gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setShowTune((v) => !v);
              }}
              className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-lg border transition cursor-pointer ${
                showTune
                  ? 'bg-slate-900 text-white border-slate-900'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <SlidersHorizontal className="w-3 h-3" />
              Tune
            </button>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onUpdateState(slot.field_key, { rotateDeg: (rotateDeg + 90) % 360 });
                }}
                title={`Rotate 90° (${rotateDeg}°)`}
                className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
              >
                <RotateCw className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onClear(slot.field_key);
                }}
                title="Remove image"
                className="p-1.5 rounded-lg bg-red-50 hover:bg-red-100 text-red-600 cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {showTune && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="rounded-lg bg-slate-50 border border-slate-200 p-2 space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() =>
                    onUpdateState(slot.field_key, { mode: isSig ? 'photo' : 'signature' })
                  }
                  className={`text-[11px] font-semibold px-2 py-1 rounded-md border transition cursor-pointer ${
                    isSig
                      ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                      : 'bg-amber-50 text-amber-900 border-amber-200'
                  }`}
                >
                  {isSig ? 'Transparent Ink' : 'Photo Mode'}
                </button>

                {!isSig && (
                  <button
                    type="button"
                    onClick={() => onUpdateState(slot.field_key, { smartCrop: !smartCrop })}
                    className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md border cursor-pointer ${
                      smartCrop
                        ? 'bg-slate-900 text-white border-slate-900'
                        : 'bg-white text-slate-600 border-slate-200'
                    }`}
                  >
                    <Crop className="w-3 h-3" />
                    {smartCrop ? 'Smart Crop' : 'Full Fit'}
                  </button>
                )}
              </div>

              {isSig && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold text-slate-600">Ink:</span>
                  <input
                    type="range"
                    min={155}
                    max={242}
                    value={threshold}
                    onChange={(e) =>
                      onUpdateState(slot.field_key, { threshold: Number(e.target.value) })
                    }
                    className="flex-1 accent-emerald-600 cursor-pointer"
                  />
                  <span className="text-[10px] font-mono text-slate-500 w-6 text-right">
                    {threshold}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function MediaStudio({
  imageFields,
  mediaSlots,
  pasteTarget,
  onSelectPasteTarget,
  onFileChange,
  onUpdateSlotState,
  onClearSlot,
  onOpenMapper,
}) {
  if (!imageFields || imageFields.length === 0) {
    return (
      <div className="pt-2 border-t border-slate-100 flex items-center justify-end">
        <button
          type="button"
          onClick={onOpenMapper}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 transition cursor-pointer"
        >
          <Sliders className="w-3.5 h-3.5" />
          Need to add a photo or signature? → Adjust Boxes
        </button>
      </div>
    );
  }

  return (
    <div className="pt-4 border-t border-slate-100 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Photos &amp; Signatures
        </h3>

        {imageFields.length > 1 && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="text-slate-400">Ctrl+V into:</span>
            {imageFields.map((slot) => (
              <button
                key={slot.field_key}
                type="button"
                onClick={() => onSelectPasteTarget(slot.field_key)}
                className={`px-2 py-0.5 rounded-md font-semibold transition cursor-pointer ${
                  pasteTarget === slot.field_key
                    ? 'bg-slate-900 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {slot.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {imageFields.map((slot) => (
          <MediaSlotCard
            key={slot.field_key}
            slot={slot}
            state={mediaSlots[slot.field_key]}
            isPasteTarget={pasteTarget === slot.field_key}
            showPasteHighlight={imageFields.length > 1}
            onSelectPasteTarget={onSelectPasteTarget}
            onFileChange={onFileChange}
            onUpdateState={onUpdateSlotState}
            onClear={onClearSlot}
          />
        ))}
      </div>
    </div>
  );
}

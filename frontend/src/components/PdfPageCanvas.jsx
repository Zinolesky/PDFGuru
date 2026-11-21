import React, { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker;

export default function PdfPageCanvas({
  pdfUrl,
  pageNumber = 1,
  fallbackImageUrl = null,
  onPageDimensions = null,
  zoom = 1,
  touchNone = false,
  children,
  interactiveProps = {},
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [useFallbackImg, setUseFallbackImg] = useState(false);
  const [aspectRatio, setAspectRatio] = useState(842 / 595);

  useEffect(() => {
    let isCancelled = false;
    let renderTask = null;

    async function renderPdfPage() {
      if (!pdfUrl) return;
      setLoading(true);
      setUseFallbackImg(false);

      try {
        const loadingTask = pdfjsLib.getDocument(pdfUrl);
        const pdfDoc = await loadingTask.promise;
        if (isCancelled) return;

        const targetPage = Math.max(1, Math.min(pdfDoc.numPages, pageNumber));
        const page = await pdfDoc.getPage(targetPage);
        if (isCancelled) return;

        const baseViewport = page.getViewport({ scale: 1.0 });
        setAspectRatio(baseViewport.height / baseViewport.width);
        if (onPageDimensions) {
          onPageDimensions({
            width: baseViewport.width,
            height: baseViewport.height,
            numPages: pdfDoc.numPages,
          });
        }

        const scale = Math.min(2.6, Math.max(1.65, 1.65 * zoom));
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;

        const context = canvas.getContext('2d');
        canvas.width = viewport.width;
        canvas.height = viewport.height;

        renderTask = page.render({
          canvasContext: context,
          viewport,
        });
        await renderTask.promise;
        if (!isCancelled) {
          setLoading(false);
        }
      } catch (err) {
        console.warn('[PdfPageCanvas] pdfjs render fallback:', err);
        if (!isCancelled) {
          setUseFallbackImg(true);
          setLoading(false);
        }
      }
    }

    renderPdfPage();

    return () => {
      isCancelled = true;
      if (renderTask && renderTask.cancel) {
        try {
          renderTask.cancel();
        } catch {
          // ignore cancel errors
        }
      }
    };
  }, [pdfUrl, pageNumber, zoom]);

  return (
    <div
      ref={containerRef}
      data-testid="pdf-interactive-surface"
      className={`relative bg-white shadow-xl rounded-lg overflow-hidden border border-slate-300 select-none ${
        touchNone ? 'touch-none' : ''
      }`}
      style={{
        width: `${Math.round(zoom * 100)}%`,
        aspectRatio: `${1 / aspectRatio}`,
      }}
      {...interactiveProps}
    >
      {loading && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-slate-900/10 backdrop-blur-[1px]">
          <div className="w-8 h-8 border-3 border-slate-900 border-t-transparent rounded-full animate-spin mb-2" />
          <span className="text-xs font-semibold text-slate-700 bg-white/90 px-3 py-1 rounded-full shadow">
            Rendering PDF Page {pageNumber}...
          </span>
        </div>
      )}

      {useFallbackImg && fallbackImageUrl ? (
        <img
          src={fallbackImageUrl}
          alt={`PDF Page ${pageNumber}`}
          className="w-full h-full object-contain pointer-events-none block"
          draggable={false}
        />
      ) : (
        <canvas
          ref={canvasRef}
          className="w-full h-full block pointer-events-none"
        />
      )}

      {/* Interactive Overlay Layer */}
      <div className="absolute inset-0 z-10">{children}</div>
    </div>
  );
}

"use client";

import { useRef, useState } from "react";

import type { Detection, ImageVariant } from "@/lib/api-client";
import { DEFECT_TYPE_COLOR, DEFECT_TYPE_LABEL } from "@/lib/chart-colors";

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const SCALE_STEP = 0.5;
const VIEWER_HEIGHT = 480;
const PAN_STEP = 40;

type Offset = { x: number; y: number };

type AnnotatedImageViewerProps = {
  originalUrl: string | null;
  annotatedUrl: string | null;
  annotatedAvailable: boolean;
  detections: Detection[];
  hoveredDetectionId: string | null;
  onHoverDetection: (id: string | null) => void;
};

/** FE-03/12.2: zoom, pan, original/annotated toggle, numbered bounding boxes color-coded by
 * class with a confidence tooltip, and a class legend (FE-10). Bounding boxes are drawn
 * from the same normalized [0,1] coordinates the API returns (section 10.2), positioned as
 * percentages over the rendered image — no pixel-dimension bookkeeping needed.
 */
export function AnnotatedImageViewer({
  originalUrl,
  annotatedUrl,
  annotatedAvailable,
  detections,
  hoveredDetectionId,
  onHoverDetection,
}: AnnotatedImageViewerProps) {
  const [variant, setVariant] = useState<ImageVariant>(annotatedAvailable ? "annotated" : "original");
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 });
  const dragging = useRef<{ startX: number; startY: number; origin: Offset } | null>(null);

  const activeUrl = variant === "annotated" ? annotatedUrl : originalUrl;

  function zoomIn() {
    setScale((s) => Math.min(MAX_SCALE, s + SCALE_STEP));
  }

  function zoomOut() {
    setScale((s) => {
      const next = Math.max(MIN_SCALE, s - SCALE_STEP);
      if (next === MIN_SCALE) setOffset({ x: 0, y: 0 });
      return next;
    });
  }

  function resetView() {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (scale <= MIN_SCALE) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = { startX: event.clientX, startY: event.clientY, origin: offset };
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragging.current) return;
    const dx = event.clientX - dragging.current.startX;
    const dy = event.clientY - dragging.current.startY;
    setOffset({ x: dragging.current.origin.x + dx, y: dragging.current.origin.y + dy });
  }

  function endDrag() {
    dragging.current = null;
  }

  // Keyboard equivalent of pointer-drag panning (FE-10) — only meaningful once zoomed in,
  // since at MIN_SCALE the image is already fully visible and there's nothing to pan to.
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (scale <= MIN_SCALE) return;
    const step = PAN_STEP;
    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault();
        setOffset((o) => ({ ...o, x: o.x + step }));
        break;
      case "ArrowRight":
        event.preventDefault();
        setOffset((o) => ({ ...o, x: o.x - step }));
        break;
      case "ArrowUp":
        event.preventDefault();
        setOffset((o) => ({ ...o, y: o.y + step }));
        break;
      case "ArrowDown":
        event.preventDefault();
        setOffset((o) => ({ ...o, y: o.y - step }));
        break;
      case "Home":
        event.preventDefault();
        resetView();
        break;
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex overflow-hidden rounded-md border border-border" role="group" aria-label="Image variant">
          <button
            type="button"
            aria-pressed={variant === "original"}
            onClick={() => setVariant("original")}
            className={`px-3 py-1 text-sm font-medium ${
              variant === "original" ? "bg-primary text-primary-foreground" : "hover:bg-muted"
            }`}
          >
            Original
          </button>
          <button
            type="button"
            aria-pressed={variant === "annotated"}
            disabled={!annotatedAvailable}
            onClick={() => setVariant("annotated")}
            className={`border-l border-border px-3 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
              variant === "annotated" ? "bg-primary text-primary-foreground" : "hover:bg-muted"
            }`}
          >
            Annotated
          </button>
        </div>

        <div className="inline-flex items-center gap-1" role="group" aria-label="Zoom controls">
          <button
            type="button"
            aria-label="Zoom out"
            onClick={zoomOut}
            disabled={scale <= MIN_SCALE}
            className="flex size-7 items-center justify-center rounded-md border border-border text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            −
          </button>
          <span className="w-12 text-center text-xs text-muted-foreground" aria-live="polite">
            {Math.round(scale * 100)}%
          </span>
          <button
            type="button"
            aria-label="Zoom in"
            onClick={zoomIn}
            disabled={scale >= MAX_SCALE}
            className="flex size-7 items-center justify-center rounded-md border border-border text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            +
          </button>
          <button
            type="button"
            aria-label="Reset zoom and pan"
            onClick={resetView}
            className="ml-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            Reset
          </button>
        </div>
      </div>

      <div
        role="group"
        aria-roledescription="image viewer"
        aria-label={`${variant === "annotated" ? "Annotated" : "Original"} PCB image, zoom and pan${
          scale > MIN_SCALE ? " — use arrow keys to pan, Home to reset" : ""
        }`}
        tabIndex={0}
        className="relative overflow-hidden rounded-lg border border-border bg-muted/30 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        style={{ height: VIEWER_HEIGHT, touchAction: "none", cursor: scale > MIN_SCALE ? "grab" : "default" }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onKeyDown={handleKeyDown}
      >
        {activeUrl ? (
          <div
            className="flex h-full items-center justify-center"
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
              transition: dragging.current ? "none" : "transform 0.15s ease-out",
            }}
          >
            <div className="relative inline-block">
              {/* eslint-disable-next-line @next/next/no-img-element -- blob: object URL, not a static/remote asset */}
              <img
                src={activeUrl}
                alt={variant === "annotated" ? "Annotated PCB inspection image" : "Original PCB inspection image"}
                className="block select-none"
                style={{ maxHeight: VIEWER_HEIGHT, maxWidth: "100%" }}
                draggable={false}
              />
              {variant === "annotated" && (
                <div className="pointer-events-none absolute inset-0">
                  {detections.map((detection, index) => {
                    const { x1, y1, x2, y2 } = detection.bbox;
                    const isHovered = hoveredDetectionId === detection.id;
                    const color = DEFECT_TYPE_COLOR[detection.defect_type];
                    const confidencePercent = (Number(detection.confidence) * 100).toFixed(1);
                    const tooltipId = `detection-tooltip-${detection.id}`;
                    return (
                      <button
                        key={detection.id}
                        type="button"
                        className="group/box pointer-events-auto absolute focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1"
                        style={{
                          left: `${x1 * 100}%`,
                          top: `${y1 * 100}%`,
                          width: `${(x2 - x1) * 100}%`,
                          height: `${(y2 - y1) * 100}%`,
                          border: `2px solid ${color}`,
                          outlineColor: color,
                          backgroundColor: isHovered ? `color-mix(in srgb, ${color} 25%, transparent)` : "transparent",
                        }}
                        aria-describedby={tooltipId}
                        aria-label={`Detection ${index + 1}: ${DEFECT_TYPE_LABEL[detection.defect_type]}, ${confidencePercent}% confidence`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onMouseEnter={() => onHoverDetection(detection.id)}
                        onMouseLeave={() => onHoverDetection(null)}
                        onFocus={() => onHoverDetection(detection.id)}
                        onBlur={() => onHoverDetection(null)}
                      >
                        <span
                          aria-hidden="true"
                          className="absolute -top-5 left-0 rounded px-1 text-[10px] font-semibold text-white"
                          style={{ backgroundColor: color }}
                        >
                          {index + 1}
                        </span>
                        <span
                          role="tooltip"
                          id={tooltipId}
                          className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden whitespace-nowrap rounded-md bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md group-hover/box:block group-focus-visible/box:block"
                        >
                          {DEFECT_TYPE_LABEL[detection.defect_type]} · {confidencePercent}% confidence
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {variant === "annotated" ? "Annotated image not available yet." : "Image not available."}
          </div>
        )}
      </div>

      <ClassLegend detections={detections} />
    </div>
  );
}

function ClassLegend({ detections }: { detections: Detection[] }) {
  const present = Array.from(new Set(detections.map((detection) => detection.defect_type)));
  if (present.length === 0) return null;

  return (
    <div role="list" aria-label="Defect class legend" className="flex flex-wrap gap-x-4 gap-y-1">
      {present.map((defectType) => (
        <div key={defectType} role="listitem" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span
            aria-hidden="true"
            className="size-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: DEFECT_TYPE_COLOR[defectType] }}
          />
          {DEFECT_TYPE_LABEL[defectType]}
        </div>
      ))}
    </div>
  );
}

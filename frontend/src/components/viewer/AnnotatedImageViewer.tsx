"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { annotateInspection, type BBox, type Detection, type ImageVariant } from "@/lib/api-client";
import {
  DEFECT_TYPE_COLOR,
  DEFECT_TYPE_LABEL,
  DEFECT_TYPES,
  type DefectType,
} from "@/lib/chart-colors";

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const SCALE_STEP = 0.5;
const VIEWER_HEIGHT = 480;
const PAN_STEP = 40;

type Offset = { x: number; y: number };

type AnnotatedImageViewerProps = {
  inspectionId: string;
  originalUrl: string | null;
  annotatedUrl: string | null;
  annotatedAvailable: boolean;
  detections: Detection[];
  hoveredDetectionId: string | null;
  onHoverDetection: (id: string | null) => void;
};

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Rounds to whole percentage points — plenty of precision for a manually-drawn box, and
 * keeps the keyboard-entry number inputs (below) working with clean integers.
 */
function toPercent(fraction: number): number {
  return Math.round(clamp01(fraction) * 100);
}

/** FE-03/12.2: zoom, pan, original/annotated toggle, numbered bounding boxes color-coded by
 * class with a confidence tooltip, and a class legend (FE-10). Bounding boxes are drawn
 * from the same normalized [0,1] coordinates the API returns (section 10.2), positioned as
 * percentages over the rendered image — no pixel-dimension bookkeeping needed.
 *
 * Also hosts the manual-annotation tool (FR-10, Issue 33): drawing a bbox + class for a
 * defect the model missed. Two independent input paths converge on the same draft-box state
 * — click-and-drag on the image, or the numeric X/Y percentage fields — so the tool is fully
 * operable without a pointer (FE-10's accessibility pass, Issue 24).
 */
export function AnnotatedImageViewer({
  inspectionId,
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
  const imageRef = useRef<HTMLImageElement | null>(null);

  const [annotating, setAnnotating] = useState(false);
  const [draftBbox, setDraftBbox] = useState<BBox | null>(null);
  const [draftDefectType, setDraftDefectType] = useState<DefectType>(DEFECT_TYPES[0]);
  const drawStart = useRef<{ x: number; y: number } | null>(null);

  const queryClient = useQueryClient();
  const annotateMutation = useMutation({
    mutationFn: (bbox: BBox) => annotateInspection(inspectionId, draftDefectType, bbox),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
      setDraftBbox(null);
      setAnnotating(false);
    },
  });

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

  function toggleAnnotating() {
    setAnnotating((prev) => {
      const next = !prev;
      if (next) {
        // The draw tool maps pointer position directly to the rendered image's bounding
        // rect — reset zoom/pan first so that mapping isn't also fighting a transform.
        resetView();
        if (variant !== "annotated" && annotatedAvailable) setVariant("annotated");
        setDraftBbox(null);
      }
      return next;
    });
  }

  function pointerToFraction(event: { clientX: number; clientY: number }): { x: number; y: number } | null {
    const rect = imageRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return {
      x: clamp01((event.clientX - rect.left) / rect.width),
      y: clamp01((event.clientY - rect.top) / rect.height),
    };
  }

  function handleDrawPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    const point = pointerToFraction(event);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawStart.current = point;
    setDraftBbox({ x1: point.x, y1: point.y, x2: point.x, y2: point.y });
  }

  function handleDrawPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!drawStart.current) return;
    const point = pointerToFraction(event);
    if (!point) return;
    const start = drawStart.current;
    setDraftBbox({
      x1: Math.min(start.x, point.x),
      y1: Math.min(start.y, point.y),
      x2: Math.max(start.x, point.x),
      y2: Math.max(start.y, point.y),
    });
  }

  function endDraw() {
    drawStart.current = null;
  }

  /** The keyboard-operable path (FE-10): editing these percentage fields sets/refines the
   * draft box without ever touching a pointer.
   */
  function handlePercentFieldChange(corner: keyof BBox, percent: number) {
    setDraftBbox((prev) => {
      const base = prev ?? { x1: 0.25, y1: 0.25, x2: 0.75, y2: 0.75 };
      return { ...base, [corner]: clamp01(percent / 100) };
    });
  }

  const draftBboxValid =
    draftBbox !== null && draftBbox.x1 < draftBbox.x2 && draftBbox.y1 < draftBbox.y2;

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (annotating) {
      handleDrawPointerDown(event);
      return;
    }
    if (scale <= MIN_SCALE) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = { startX: event.clientX, startY: event.clientY, origin: offset };
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (annotating) {
      handleDrawPointerMove(event);
      return;
    }
    if (!dragging.current) return;
    const dx = event.clientX - dragging.current.startX;
    const dy = event.clientY - dragging.current.startY;
    setOffset({ x: dragging.current.origin.x + dx, y: dragging.current.origin.y + dy });
  }

  function handlePointerUp() {
    if (annotating) {
      endDraw();
      return;
    }
    dragging.current = null;
  }

  // Keyboard equivalent of pointer-drag panning (FE-10) — only meaningful once zoomed in,
  // since at MIN_SCALE the image is already fully visible and there's nothing to pan to.
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (annotating || scale <= MIN_SCALE) return;
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
            disabled={scale <= MIN_SCALE || annotating}
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
            disabled={scale >= MAX_SCALE || annotating}
            className="flex size-7 items-center justify-center rounded-md border border-border text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            +
          </button>
          <button
            type="button"
            aria-label="Reset zoom and pan"
            onClick={resetView}
            disabled={annotating}
            className="ml-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            Reset
          </button>
        </div>

        <Button
          type="button"
          size="sm"
          variant={annotating ? "default" : "outline"}
          aria-pressed={annotating}
          onClick={toggleAnnotating}
        >
          {annotating ? "Cancel annotation" : "Annotate missed defect"}
        </Button>
      </div>

      <div
        role="group"
        aria-roledescription="image viewer"
        aria-label={`${variant === "annotated" ? "Annotated" : "Original"} PCB image, zoom and pan${
          scale > MIN_SCALE ? " — use arrow keys to pan, Home to reset" : ""
        }${annotating ? " — drawing a manual annotation" : ""}`}
        tabIndex={0}
        className="relative overflow-hidden rounded-lg border border-border bg-muted/30 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        style={{
          height: VIEWER_HEIGHT,
          touchAction: "none",
          cursor: annotating ? "crosshair" : scale > MIN_SCALE ? "grab" : "default",
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
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
                ref={imageRef}
                src={activeUrl}
                alt={variant === "annotated" ? "Annotated PCB inspection image" : "Original PCB inspection image"}
                className="block select-none"
                style={{ maxHeight: VIEWER_HEIGHT, maxWidth: "100%" }}
                draggable={false}
              />
              {variant === "annotated" && (
                <div
                  className="absolute inset-0"
                  style={{ pointerEvents: annotating ? "none" : "auto" }}
                >
                  {detections.map((detection, index) => {
                    const { x1, y1, x2, y2 } = detection.bbox;
                    const isHovered = hoveredDetectionId === detection.id;
                    const color = DEFECT_TYPE_COLOR[detection.defect_type];
                    const confidencePercent = (Number(detection.confidence) * 100).toFixed(1);
                    const tooltipId = `detection-tooltip-${detection.id}`;
                    const manual = detection.source === "manual";
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
                          border: `2px ${manual ? "dashed" : "solid"} ${color}`,
                          outlineColor: color,
                          backgroundColor: isHovered ? `color-mix(in srgb, ${color} 25%, transparent)` : "transparent",
                        }}
                        aria-describedby={tooltipId}
                        aria-label={`Detection ${index + 1}: ${DEFECT_TYPE_LABEL[detection.defect_type]}, ${
                          manual ? "manually annotated" : `${confidencePercent}% confidence`
                        }`}
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
                          {DEFECT_TYPE_LABEL[detection.defect_type]}
                          {manual ? " · Manually annotated" : ` · ${confidencePercent}% confidence`}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              {annotating && draftBbox && (
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute border-2 border-dashed border-foreground"
                  style={{
                    left: `${draftBbox.x1 * 100}%`,
                    top: `${draftBbox.y1 * 100}%`,
                    width: `${(draftBbox.x2 - draftBbox.x1) * 100}%`,
                    height: `${(draftBbox.y2 - draftBbox.y1) * 100}%`,
                  }}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {variant === "annotated" ? "Annotated image not available yet." : "Image not available."}
          </div>
        )}
      </div>

      {annotating && (
        <div className="flex flex-col gap-3 rounded-lg border border-border p-3" aria-label="Manual annotation tool">
          <p className="text-sm text-muted-foreground">
            Drag on the image above, or set the box edges directly — both update the same
            preview.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 sm:items-end">
            <div className="flex flex-col gap-1">
              <label htmlFor="annotation-defect-type" className="text-xs font-medium">
                Defect type
              </label>
              <select
                id="annotation-defect-type"
                value={draftDefectType}
                onChange={(event) => setDraftDefectType(event.target.value as DefectType)}
                className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {DEFECT_TYPES.map((defectType) => (
                  <option key={defectType} value={defectType}>
                    {DEFECT_TYPE_LABEL[defectType]}
                  </option>
                ))}
              </select>
            </div>
            {(["x1", "y1", "x2", "y2"] as const).map((corner) => (
              <div key={corner} className="flex flex-col gap-1">
                <label htmlFor={`annotation-${corner}`} className="text-xs font-medium uppercase">
                  {corner} (%)
                </label>
                <input
                  id={`annotation-${corner}`}
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={draftBbox ? toPercent(draftBbox[corner]) : ""}
                  onChange={(event) => handlePercentFieldChange(corner, Number(event.target.value))}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>
            ))}
          </div>
          {annotateMutation.isError && (
            <p className="text-sm text-destructive">Could not save this annotation. Check the box edges and try again.</p>
          )}
          <div>
            <Button
              type="button"
              size="sm"
              disabled={!draftBboxValid || annotateMutation.isPending}
              onClick={() => draftBbox && annotateMutation.mutate(draftBbox)}
            >
              {annotateMutation.isPending ? "Saving…" : "Add annotation"}
            </Button>
          </div>
        </div>
      )}

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

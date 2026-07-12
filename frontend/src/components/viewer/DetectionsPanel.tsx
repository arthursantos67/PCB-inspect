"use client";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import type { Detection } from "@/lib/api-client";

type DetectionsPanelProps = {
  detections: Detection[];
  hoveredDetectionId: string | null;
  onHoverDetection: (id: string | null) => void;
};

/** Detections list synchronized with the viewer (FE-03): hovering/focusing a row highlights
 * the matching bounding box and vice versa, via the shared `hoveredDetectionId` state lifted
 * to the detail page.
 */
export function DetectionsPanel({ detections, hoveredDetectionId, onHoverDetection }: DetectionsPanelProps) {
  if (detections.length === 0) {
    return <p className="text-sm text-muted-foreground">No reportable defects detected.</p>;
  }

  return (
    <ul className="flex flex-col gap-1.5" aria-label="Detected defects">
      {detections.map((detection, index) => {
        const isHovered = hoveredDetectionId === detection.id;
        return (
          <li key={detection.id}>
            <button
              type="button"
              className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                isHovered ? "border-primary bg-muted" : "border-border hover:bg-muted/50"
              }`}
              onMouseEnter={() => onHoverDetection(detection.id)}
              onMouseLeave={() => onHoverDetection(null)}
              onFocus={() => onHoverDetection(detection.id)}
              onBlur={() => onHoverDetection(null)}
            >
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold"
                >
                  {index + 1}
                </span>
                <DefectBadge defectType={detection.defect_type} />
              </span>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {(Number(detection.confidence) * 100).toFixed(1)}% confidence
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

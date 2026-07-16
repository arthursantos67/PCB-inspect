"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { Button } from "@/components/ui/button";
import { submitDetectionFeedback, type Detection } from "@/lib/api-client";

type DetectionsPanelProps = {
  inspectionId: string;
  detections: Detection[];
  hoveredDetectionId: string | null;
  onHoverDetection: (id: string | null) => void;
};

const REVIEW_LABEL: Record<Detection["review"], string> = {
  unreviewed: "Unreviewed",
  confirmed: "Confirmed",
  false_positive: "False positive",
};

/** Detections list synchronized with the viewer (FE-03): hovering/focusing a row highlights
 * the matching bounding box and vice versa, via the shared `hoveredDetectionId` state lifted
 * to the detail page. Also hosts per-detection feedback (FR-10, Issue 33): confirm/false
 * positive, independent of the analysis-level review.
 */
export function DetectionsPanel({
  inspectionId,
  detections,
  hoveredDetectionId,
  onHoverDetection,
}: DetectionsPanelProps) {
  const queryClient = useQueryClient();
  const feedbackMutation = useMutation({
    mutationFn: ({ detectionId, review }: { detectionId: string; review: "confirmed" | "false_positive" }) =>
      submitDetectionFeedback(detectionId, review),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
    },
  });

  if (detections.length === 0) {
    return <p className="text-sm text-muted-foreground">No reportable defects detected.</p>;
  }

  return (
    <ul className="flex flex-col gap-1.5" aria-label="Detected defects">
      {detections.map((detection, index) => {
        const isHovered = hoveredDetectionId === detection.id;
        const isPending =
          feedbackMutation.isPending && feedbackMutation.variables?.detectionId === detection.id;
        return (
          <li key={detection.id}>
            <div
              className={`flex flex-col gap-2 rounded-md border px-3 py-2 transition-colors ${
                isHovered ? "border-primary bg-muted" : "border-border hover:bg-muted/50"
              }`}
            >
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 text-left text-sm"
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
                  {detection.source === "manual" && (
                    <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      Manual
                    </span>
                  )}
                </span>
                <span className="whitespace-nowrap text-xs text-muted-foreground">
                  {detection.source === "manual"
                    ? "Manually annotated"
                    : `${(Number(detection.confidence) * 100).toFixed(1)}% confidence`}
                </span>
              </button>

              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  Feedback: {REVIEW_LABEL[detection.review]}
                </span>
                <div className="flex gap-1.5" role="group" aria-label={`Feedback for detection ${index + 1}`}>
                  <Button
                    type="button"
                    size="sm"
                    variant={detection.review === "confirmed" ? "default" : "outline"}
                    disabled={isPending}
                    onClick={() =>
                      feedbackMutation.mutate({ detectionId: detection.id, review: "confirmed" })
                    }
                  >
                    Confirm
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={detection.review === "false_positive" ? "default" : "outline"}
                    disabled={isPending}
                    onClick={() =>
                      feedbackMutation.mutate({ detectionId: detection.id, review: "false_positive" })
                    }
                  >
                    False positive
                  </Button>
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

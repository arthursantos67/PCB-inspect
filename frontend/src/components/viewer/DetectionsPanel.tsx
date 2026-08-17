"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";
import { submitDetectionFeedback, type Detection } from "@/lib/api-client";
import { DEFECT_TYPE_COLOR } from "@/lib/chart-colors";

type DetectionsPanelProps = {
  inspectionId: string;
  detections: Detection[];
  hoveredDetectionId: string | null;
  onHoverDetection: (id: string | null) => void;
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
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const feedbackMutation = useMutation({
    mutationFn: ({ detectionId, review }: { detectionId: string; review: "confirmed" | "false_positive" }) =>
      submitDetectionFeedback(detectionId, review),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
    },
  });

  if (detections.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("detections.empty")}</p>;
  }

  return (
    <ul className="flex flex-col gap-1.5" aria-label={t("detections.listLabel")}>
      {detections.map((detection, index) => {
        const isHovered = hoveredDetectionId === detection.id;
        const isPending =
          feedbackMutation.isPending && feedbackMutation.variables?.detectionId === detection.id;
        return (
          <li key={detection.id}>
            <div
              className={`relative overflow-hidden rounded-md border px-3 py-2.5 transition-colors ${
                isHovered ? "border-brand bg-accent" : "border-border hover:bg-accent/50"
              }`}
            >
              <button
                type="button"
                className="flex w-full items-center gap-2 text-left"
                onMouseEnter={() => onHoverDetection(detection.id)}
                onMouseLeave={() => onHoverDetection(null)}
                onFocus={() => onHoverDetection(detection.id)}
                onBlur={() => onHoverDetection(null)}
              >
                {/* Same number as the box on the image and the analysis passage below. */}
                <span
                  aria-hidden="true"
                  className="readout flex size-5 shrink-0 items-center justify-center rounded-[4px] border border-border bg-card text-[0.6875rem] font-semibold"
                >
                  {index + 1}
                </span>
                <DefectBadge defectType={detection.defect_type} />
                {detection.source === "manual" && (
                  <span className="label-channel border-l border-border pl-2">
                    {t("detections.manual")}
                  </span>
                )}
                <span className="readout ml-auto text-[0.75rem] font-semibold whitespace-nowrap">
                  {detection.source === "manual" ? (
                    <span className="font-normal text-muted-foreground">
                      {t("detections.drawnByHand")}
                    </span>
                  ) : (
                    <>
                      {(Number(detection.confidence) * 100).toFixed(1)}
                      <span className="font-normal text-muted-foreground">%</span>
                    </>
                  )}
                </span>
              </button>

              {/* The chosen option stays visibly pressed in a dimmed gray and its label
                  switches to the past tense, so a row that
                  was already reviewed reads as reviewed with no separate status line. */}
              <div
                className="mt-2 flex gap-1.5"
                role="group"
                aria-label={t("detections.feedbackGroup", { index: index + 1 })}
              >
                <Button
                  type="button"
                  size="sm"
                  aria-pressed={detection.review === "confirmed"}
                  variant={detection.review === "confirmed" ? "selected" : "outline"}
                  disabled={isPending}
                  onClick={() =>
                    feedbackMutation.mutate({ detectionId: detection.id, review: "confirmed" })
                  }
                >
                  {detection.review === "confirmed"
                    ? t("detections.confirmed")
                    : t("detections.confirm")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  aria-pressed={detection.review === "false_positive"}
                  variant={detection.review === "false_positive" ? "selected" : "outline"}
                  disabled={isPending}
                  onClick={() =>
                    feedbackMutation.mutate({ detectionId: detection.id, review: "false_positive" })
                  }
                >
                  {detection.review === "false_positive"
                    ? t("detections.markedFalsePositive")
                    : t("detections.falsePositive")}
                </Button>
              </div>

              {/* Confidence read as a meter along the row's bottom edge: a column of these is
                  scannable as "how sure was the model", which a column of numbers is not. */}
              {detection.source !== "manual" && (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-border/60"
                >
                  <span
                    className="block h-full rounded-r-full transition-[width] duration-500"
                    style={{
                      width: `${Math.min(100, Number(detection.confidence) * 100)}%`,
                      backgroundColor: DEFECT_TYPE_COLOR[detection.defect_type],
                    }}
                  />
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

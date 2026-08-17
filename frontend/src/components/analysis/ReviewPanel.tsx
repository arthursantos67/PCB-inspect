"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";
import { reviewAnalysis, type AnalysisReview } from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

type ReviewPanelProps = {
  inspectionId: string;
  analysisId: string;
  reviewStatus: "PENDING" | "VALIDATED" | "REJECTED";
  reviews: AnalysisReview[];
};

/** Validate/reject an analysis with an optional comment (FR-10, UC-8) — the analysis-level
 * counterpart to `DetectionsPanel`'s per-detection feedback. History is shown below so the
 * action is visibly "queryable later" without leaving the page.
 */
export function ReviewPanel({ inspectionId, analysisId, reviewStatus, reviews }: ReviewPanelProps) {
  const { t } = useI18n();
  const [comment, setComment] = useState("");
  const queryClient = useQueryClient();

  const reviewMutation = useMutation({
    mutationFn: (action: "validated" | "rejected") => reviewAnalysis(analysisId, action, comment),
    onSuccess: () => {
      setComment("");
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
    },
  });

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="label-channel">{t("review.title")}</p>
          <p className="mt-1 text-[0.8125rem] font-medium">{t(`reviewStatus.${reviewStatus}`)}</p>
        </div>
        {/* The decision already on record shows as pressed, in a dimmed gray, with its label
            in the past tense. Both stay clickable: reviewing
            again is allowed and appends to the history below. */}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            aria-pressed={reviewStatus === "VALIDATED"}
            variant={reviewStatus === "VALIDATED" ? "selected" : "brand"}
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("validated")}
          >
            {reviewStatus === "VALIDATED" ? t("review.validated") : t("review.validate")}
          </Button>
          <Button
            type="button"
            size="sm"
            aria-pressed={reviewStatus === "REJECTED"}
            variant={reviewStatus === "REJECTED" ? "selected" : "outline"}
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("rejected")}
          >
            {reviewStatus === "REJECTED" ? t("review.rejected") : t("review.reject")}
          </Button>
        </div>
      </div>

      <div className="field">
        <label htmlFor="review-comment">{t("review.comment")}</label>
        <textarea
          id="review-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          rows={2}
          className="control h-auto py-1.5 leading-relaxed"
          placeholder={t("review.commentPlaceholder")}
        />
      </div>

      {reviewMutation.isError && (
        <p className="text-[0.8125rem] text-status-critical">
          {t("review.failed")}
        </p>
      )}

      {reviews.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <p className="label-channel">{t("review.history")}</p>
          <ul className="flex flex-col gap-1.5">
            {reviews.map((review) => (
              <li key={review.id} className="text-[0.75rem] text-muted-foreground">
                <span className="font-medium text-foreground">
                  {t(`review.action.${review.action}`)}
                </span>
                <span className="readout mx-2 text-[0.6875rem]">
                  {formatTimestamp(review.created_at)}
                </span>
                {review.comment && <span>{review.comment}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

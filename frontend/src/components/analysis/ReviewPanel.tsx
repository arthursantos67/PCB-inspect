"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { reviewAnalysis, type AnalysisReview } from "@/lib/api-client";

type ReviewPanelProps = {
  inspectionId: string;
  analysisId: string;
  reviewStatus: "PENDING" | "VALIDATED" | "REJECTED";
  reviews: AnalysisReview[];
};

const STATUS_LABEL: Record<ReviewPanelProps["reviewStatus"], string> = {
  PENDING: "Pending review",
  VALIDATED: "Validated",
  REJECTED: "Rejected",
};

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Validate/reject an analysis with an optional comment (FR-10, UC-8) — the analysis-level
 * counterpart to `DetectionsPanel`'s per-detection feedback. History is shown below so the
 * action is visibly "queryable later" without leaving the page.
 */
export function ReviewPanel({ inspectionId, analysisId, reviewStatus, reviews }: ReviewPanelProps) {
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
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Review status: {STATUS_LABEL[reviewStatus]}</span>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("validated")}
          >
            Validate
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("rejected")}
          >
            Reject
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="review-comment" className="text-xs font-medium text-muted-foreground">
          Comment (optional)
        </label>
        <textarea
          id="review-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          rows={2}
          className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          placeholder="Why is this being validated or rejected?"
        />
      </div>

      {reviewMutation.isError && (
        <p className="text-sm text-destructive">Could not record this review. Please try again.</p>
      )}

      {reviews.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">History</span>
          <ul className="flex flex-col gap-1.5">
            {reviews.map((review) => (
              <li key={review.id} className="text-xs text-muted-foreground">
                <span className="font-medium capitalize text-foreground">{review.action}</span>
                {" · "}
                {formatDateTime(review.created_at)}
                {review.comment && <span> — {review.comment}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

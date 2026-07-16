// Search/history screen filter state (FE-04, PRD section 11.3/12.2) and its URL
// serialization — kept separate from the page component so both `FilterBar` and the
// `/inspections` page can share the same shape/round-trip without importing each other.

import type { BoardDispositionDecision, ImageStatus } from "@/lib/api-client";
import { IMAGE_STATUSES } from "@/components/dashboard/StatusBadge";
import { DEFECT_TYPES, SEVERITIES, type DefectType, type Severity } from "@/lib/chart-colors";

export type ReviewStatusFilter = "PENDING" | "VALIDATED" | "REJECTED";

// Fixed enumeration order for the review-status/disposition filter dropdowns (FE-04, FR-10).
export const REVIEW_STATUSES: readonly ReviewStatusFilter[] = ["PENDING", "VALIDATED", "REJECTED"];
export const REVIEW_STATUS_LABEL: Record<ReviewStatusFilter, string> = {
  PENDING: "Pending review",
  VALIDATED: "Validated",
  REJECTED: "Rejected",
};

export const BOARD_DISPOSITIONS: readonly BoardDispositionDecision[] = [
  "approved",
  "rework",
  "discarded",
];
export const BOARD_DISPOSITION_LABEL: Record<BoardDispositionDecision, string> = {
  approved: "Approved",
  rework: "Needs rework",
  discarded: "Discarded",
};

export type InspectionFilterValues = {
  defect_type: DefectType[];
  batch_number: string;
  board_number: string;
  status: ImageStatus | "";
  severity: Severity | "";
  review_status: ReviewStatusFilter | "";
  disposition: BoardDispositionDecision | "";
  date_from: string;
  date_to: string;
};

export const EMPTY_INSPECTION_FILTERS: InspectionFilterValues = {
  defect_type: [],
  batch_number: "",
  board_number: "",
  status: "",
  severity: "",
  review_status: "",
  disposition: "",
  date_from: "",
  date_to: "",
};

function isDefectType(value: string): value is DefectType {
  return (DEFECT_TYPES as readonly string[]).includes(value);
}

function isImageStatus(value: string): value is ImageStatus {
  return (IMAGE_STATUSES as readonly string[]).includes(value);
}

function isSeverity(value: string): value is Severity {
  return (SEVERITIES as readonly string[]).includes(value);
}

function isReviewStatus(value: string): value is ReviewStatusFilter {
  return (REVIEW_STATUSES as readonly string[]).includes(value);
}

function isBoardDisposition(value: string): value is BoardDispositionDecision {
  return (BOARD_DISPOSITIONS as readonly string[]).includes(value);
}

export function filtersFromSearchParams(params: URLSearchParams): InspectionFilterValues {
  const status = params.get("status") ?? "";
  const severity = params.get("severity") ?? "";
  const reviewStatus = params.get("review_status") ?? "";
  const disposition = params.get("disposition") ?? "";
  return {
    defect_type: params.getAll("defect_type").filter(isDefectType),
    batch_number: params.get("batch_number") ?? "",
    board_number: params.get("board_number") ?? "",
    status: isImageStatus(status) ? status : "",
    severity: isSeverity(severity) ? severity : "",
    review_status: isReviewStatus(reviewStatus) ? reviewStatus : "",
    disposition: isBoardDisposition(disposition) ? disposition : "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
  };
}

export function filtersToSearchParams(filters: InspectionFilterValues): URLSearchParams {
  const params = new URLSearchParams();
  for (const defectType of filters.defect_type) params.append("defect_type", defectType);
  if (filters.batch_number) params.set("batch_number", filters.batch_number);
  if (filters.board_number) params.set("board_number", filters.board_number);
  if (filters.status) params.set("status", filters.status);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.review_status) params.set("review_status", filters.review_status);
  if (filters.disposition) params.set("disposition", filters.disposition);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  return params;
}

export function hasActiveFilters(filters: InspectionFilterValues): boolean {
  return (
    filters.defect_type.length > 0 ||
    filters.batch_number !== "" ||
    filters.board_number !== "" ||
    filters.status !== "" ||
    filters.severity !== "" ||
    filters.review_status !== "" ||
    filters.disposition !== "" ||
    filters.date_from !== "" ||
    filters.date_to !== ""
  );
}

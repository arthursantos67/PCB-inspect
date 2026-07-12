// Search/history screen filter state (FE-04, PRD section 11.3/12.2) and its URL
// serialization — kept separate from the page component so both `FilterBar` and the
// `/inspections` page can share the same shape/round-trip without importing each other.

import type { ImageStatus } from "@/lib/api-client";
import { IMAGE_STATUSES } from "@/components/dashboard/StatusBadge";
import { DEFECT_TYPES, SEVERITIES, type DefectType, type Severity } from "@/lib/chart-colors";

export type InspectionFilterValues = {
  defect_type: DefectType[];
  batch_number: string;
  board_number: string;
  status: ImageStatus | "";
  severity: Severity | "";
  date_from: string;
  date_to: string;
};

export const EMPTY_INSPECTION_FILTERS: InspectionFilterValues = {
  defect_type: [],
  batch_number: "",
  board_number: "",
  status: "",
  severity: "",
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

export function filtersFromSearchParams(params: URLSearchParams): InspectionFilterValues {
  const status = params.get("status") ?? "";
  const severity = params.get("severity") ?? "";
  return {
    defect_type: params.getAll("defect_type").filter(isDefectType),
    batch_number: params.get("batch_number") ?? "",
    board_number: params.get("board_number") ?? "",
    status: isImageStatus(status) ? status : "",
    severity: isSeverity(severity) ? severity : "",
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
    filters.date_from !== "" ||
    filters.date_to !== ""
  );
}

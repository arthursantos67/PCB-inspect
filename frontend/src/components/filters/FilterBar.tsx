"use client";

import { useEffect, useRef, useState } from "react";

import { IMAGE_STATUSES, StatusLegend } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/contexts/I18nContext";
import { DEFECT_TYPES, DEFECT_TYPE_COLOR, SEVERITIES, type DefectType } from "@/lib/chart-colors";
import {
  BOARD_DISPOSITIONS,
  EMPTY_INSPECTION_FILTERS,
  hasActiveFilters,
  REVIEW_STATUSES,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const TEXT_COMMIT_DELAY_MS = 400;

// Every control in this bar wears the same shell (`.control` in globals.css) whether it is a
// native select, a native date field or the Input primitive, so a row of six filters reads as
// one instrument rather than six borrowed widgets.
const SELECT_CLASS = "control";

/** Local draft + debounced commit for one text filter field. Re-syncing `draft` from
 * `externalValue` also cancels any in-flight timer — otherwise a filter typed just before an
 * external reset (Clear filters, browser back/forward, a direct link) would still fire a few
 * hundred ms later and silently resurrect it.
 */
function useDebouncedFilterField(
  externalValue: string,
  commit: (next: string) => void,
  delayMs: number
): [string, (next: string) => void] {
  const [draft, setDraft] = useState(externalValue);
  const commitRef = useRef(commit);
  commitRef.current = commit;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setDraft(externalValue);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, [externalValue]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  function handleChange(next: string) {
    setDraft(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => commitRef.current(next), delayMs);
  }

  return [draft, handleChange];
}

/** Combinable filters for the search/history screen (FE-04, PRD section 12.2). Fully
 * controlled — the parent owns filter state (synced to the URL for shareable links) and
 * passes it back down. Text fields keep a local draft so each keystroke doesn't trigger a
 * fetch; every other control commits immediately.
 *
 * `mode` follows the two levels the inspections screen now has:
 * the batch list only supports what `GET /api/v1/batches` can actually filter on, so
 * the board-level controls are hidden there rather than shown doing nothing. `reports` keeps
 * every board-level control but drops the batch/board text inputs, because the reports screen
 * picks both from lists of what actually exists and two ways to say the same thing
 * would only let them contradict each other.
 */
export function FilterBar({
  value,
  onChange,
  mode = "boards",
}: {
  value: InspectionFilterValues;
  onChange: (next: InspectionFilterValues) => void;
  mode?: "boards" | "batches" | "reports";
}) {
  const { t } = useI18n();
  const showBoardFilters = mode !== "batches";
  const showScopeInputs = mode !== "reports";
  const [batchDraft, handleBatchChange] = useDebouncedFilterField(
    value.batch_number,
    (next) => onChange({ ...value, batch_number: next }),
    TEXT_COMMIT_DELAY_MS
  );
  const [boardDraft, handleBoardChange] = useDebouncedFilterField(
    value.board_number,
    (next) => onChange({ ...value, board_number: next }),
    TEXT_COMMIT_DELAY_MS
  );

  function toggleDefectType(defectType: DefectType) {
    const next = value.defect_type.includes(defectType)
      ? value.defect_type.filter((item) => item !== defectType)
      : [...value.defect_type, defectType];
    onChange({ ...value, defect_type: next });
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 shadow-panel">
      <div className="grid grid-cols-1 gap-x-4 gap-y-3.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {showScopeInputs && (
          <div className="field">
            <Label htmlFor="filter-batch">{t("filters.batch")}</Label>
            <Input
              id="filter-batch"
              value={batchDraft}
              onChange={(event) => handleBatchChange(event.target.value)}
              placeholder={t("filters.batchPlaceholder")}
            />
          </div>
        )}
        {showBoardFilters && (
          <>
            {showScopeInputs && (
              <div className="field">
                <Label htmlFor="filter-board">{t("filters.board")}</Label>
                <Input
                  id="filter-board"
                  value={boardDraft}
                  onChange={(event) => handleBoardChange(event.target.value)}
                  placeholder={t("filters.boardPlaceholder")}
                />
              </div>
            )}
            <div className="field">
              <Label htmlFor="filter-status">{t("filters.status")}</Label>
              <select
                id="filter-status"
                className={SELECT_CLASS}
                value={value.status}
                onChange={(event) =>
                  onChange({
                    ...value,
                    status: event.target.value as InspectionFilterValues["status"],
                  })
                }
              >
                <option value="">{t("filters.allStatuses")}</option>
                {IMAGE_STATUSES.map((status) => (
                  <option key={status} value={status} title={t(`statusDescription.${status}`)}>
                    {t(`status.${status}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <Label htmlFor="filter-severity">{t("filters.severity")}</Label>
              <select
                id="filter-severity"
                className={SELECT_CLASS}
                value={value.severity}
                onChange={(event) =>
                  onChange({
                    ...value,
                    severity: event.target.value as InspectionFilterValues["severity"],
                  })
                }
              >
                <option value="">{t("filters.allSeverities")}</option>
                {SEVERITIES.map((severity) => (
                  <option key={severity} value={severity}>
                    {t(`severity.${severity}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <Label htmlFor="filter-review-status">{t("filters.reviewStatus")}</Label>
              <select
                id="filter-review-status"
                className={SELECT_CLASS}
                value={value.review_status}
                onChange={(event) =>
                  onChange({
                    ...value,
                    review_status: event.target.value as InspectionFilterValues["review_status"],
                  })
                }
              >
                <option value="">{t("filters.allReviewStatuses")}</option>
                {REVIEW_STATUSES.map((reviewStatus) => (
                  <option key={reviewStatus} value={reviewStatus}>
                    {t(`reviewStatus.${reviewStatus}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <Label htmlFor="filter-disposition">{t("filters.disposition")}</Label>
              <select
                id="filter-disposition"
                className={SELECT_CLASS}
                title={t("filters.dispositionHint")}
                value={value.disposition}
                onChange={(event) =>
                  onChange({
                    ...value,
                    disposition: event.target.value as InspectionFilterValues["disposition"],
                  })
                }
              >
                <option value="">{t("filters.allDispositions")}</option>
                {BOARD_DISPOSITIONS.map((disposition) => (
                  <option key={disposition} value={disposition}>
                    {t(`disposition.${disposition}`)}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
        <div className="field">
          <Label htmlFor="filter-date-from">{t("filters.dateFrom")}</Label>
          <Input
            id="filter-date-from"
            type="date"
            value={value.date_from}
            onChange={(event) => onChange({ ...value, date_from: event.target.value })}
          />
        </div>
        <div className="field">
          <Label htmlFor="filter-date-to">{t("filters.dateTo")}</Label>
          <Input
            id="filter-date-to"
            type="date"
            value={value.date_to}
            onChange={(event) => onChange({ ...value, date_to: event.target.value })}
          />
        </div>
      </div>

      {showBoardFilters && (
        <div className="field border-t border-border pt-3.5">
          <span id="filter-defect-type-label" className="field-label">
            {t("filters.defectType")}
          </span>
          {/* Each option carries the class's own hue beside it, the same hue the trend and
              distribution use, so picking a filter here and reading a chart there are the
              same act of identification. */}
          <div
            role="group"
            aria-labelledby="filter-defect-type-label"
            className="flex flex-wrap gap-x-4 gap-y-2"
          >
            {DEFECT_TYPES.map((defectType) => (
              <label
                key={defectType}
                className="flex cursor-pointer items-center gap-2 text-[0.8125rem] text-foreground"
              >
                <input
                  type="checkbox"
                  className="control-check"
                  checked={value.defect_type.includes(defectType)}
                  onChange={() => toggleDefectType(defectType)}
                />
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-[2px]"
                  style={{ backgroundColor: DEFECT_TYPE_COLOR[defectType] }}
                />
                {t(`defect.${defectType}`)}
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3.5">
        <StatusLegend />
        {hasActiveFilters(value) && (
          <Button variant="outline" size="sm" onClick={() => onChange(EMPTY_INSPECTION_FILTERS)}>
            {t("filters.clear")}
          </Button>
        )}
      </div>
    </div>
  );
}

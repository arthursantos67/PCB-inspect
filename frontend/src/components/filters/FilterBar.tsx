"use client";

import { useEffect, useRef, useState } from "react";

import { IMAGE_STATUSES, STATUS_LABEL } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DEFECT_TYPES,
  DEFECT_TYPE_LABEL,
  SEVERITIES,
  SEVERITY_LABEL,
  type DefectType,
} from "@/lib/chart-colors";
import {
  EMPTY_INSPECTION_FILTERS,
  hasActiveFilters,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const TEXT_COMMIT_DELAY_MS = 400;

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

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
 */
export function FilterBar({
  value,
  onChange,
}: {
  value: InspectionFilterValues;
  onChange: (next: InspectionFilterValues) => void;
}) {
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
    <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-batch">Batch</Label>
          <Input
            id="filter-batch"
            value={batchDraft}
            onChange={(event) => handleBatchChange(event.target.value)}
            placeholder="Batch number"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-board">Board</Label>
          <Input
            id="filter-board"
            value={boardDraft}
            onChange={(event) => handleBoardChange(event.target.value)}
            placeholder="Board number"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-status">Status</Label>
          <select
            id="filter-status"
            className={SELECT_CLASS}
            value={value.status}
            onChange={(event) =>
              onChange({ ...value, status: event.target.value as InspectionFilterValues["status"] })
            }
          >
            <option value="">All statuses</option>
            {IMAGE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-severity">Severity</Label>
          <select
            id="filter-severity"
            className={SELECT_CLASS}
            value={value.severity}
            onChange={(event) =>
              onChange({ ...value, severity: event.target.value as InspectionFilterValues["severity"] })
            }
          >
            <option value="">All severities</option>
            {SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {SEVERITY_LABEL[severity]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-date-from">From</Label>
          <Input
            id="filter-date-from"
            type="date"
            value={value.date_from}
            onChange={(event) => onChange({ ...value, date_from: event.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-date-to">To</Label>
          <Input
            id="filter-date-to"
            type="date"
            value={value.date_to}
            onChange={(event) => onChange({ ...value, date_to: event.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span id="filter-defect-type-label" className="text-sm font-medium">
          Defect type
        </span>
        <div role="group" aria-labelledby="filter-defect-type-label" className="flex flex-wrap gap-x-4 gap-y-2">
          {DEFECT_TYPES.map((defectType) => (
            <label key={defectType} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={value.defect_type.includes(defectType)}
                onChange={() => toggleDefectType(defectType)}
              />
              {DEFECT_TYPE_LABEL[defectType]}
            </label>
          ))}
        </div>
      </div>

      {hasActiveFilters(value) && (
        <div>
          <Button variant="outline" size="sm" onClick={() => onChange(EMPTY_INSPECTION_FILTERS)}>
            Clear filters
          </Button>
        </div>
      )}
    </div>
  );
}

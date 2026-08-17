"use client";

import { useI18n } from "@/contexts/I18nContext";
import { DEFECT_TYPE_COLOR, type DefectType } from "@/lib/chart-colors";

/** Defect-class chip (FE-02/FE-10): identity is never color-alone — the square carries the
 * fixed categorical hue, the text label carries the meaning. `count`, when given, appends how
 * many times the class occurs in the row's scope (used by the batch list).
 *
 * The swatch is a square, not a dot, so it matches the mark shape used in chart legends,
 * tooltips and data tables: the same class looks the same everywhere in the product.
 */
export function DefectBadge({ defectType, count }: { defectType: DefectType; count?: number }) {
  const { t } = useI18n();
  return (
    <span className="inline-flex h-[1.375rem] items-center gap-1.5 rounded-[5px] border border-border bg-card px-1.5 text-[0.6875rem] font-medium whitespace-nowrap text-foreground">
      <span
        aria-hidden="true"
        className="size-2 shrink-0 rounded-[2px]"
        style={{ backgroundColor: DEFECT_TYPE_COLOR[defectType] }}
      />
      {t(`defect.${defectType}`)}
      {count != null && <span className="readout text-muted-foreground">{count}</span>}
    </span>
  );
}

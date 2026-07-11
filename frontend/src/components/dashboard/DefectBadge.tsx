import { DEFECT_TYPE_COLOR, DEFECT_TYPE_LABEL, type DefectType } from "@/lib/chart-colors";

/** Defect-class badge (FE-02/FE-10): identity is never color-alone — the dot carries the
 * fixed categorical hue, the text label carries the meaning.
 */
export function DefectBadge({ defectType }: { defectType: DefectType }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium whitespace-nowrap text-foreground">
      <span
        aria-hidden="true"
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: DEFECT_TYPE_COLOR[defectType] }}
      />
      {DEFECT_TYPE_LABEL[defectType]}
    </span>
  );
}

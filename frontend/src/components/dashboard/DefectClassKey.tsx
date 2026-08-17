"use client";

import { useI18n } from "@/contexts/I18nContext";
import { DEFECT_TYPES, DEFECT_TYPE_COLOR, type DefectType } from "@/lib/chart-colors";
import { cn } from "@/lib/utils";

/** One key for the two class-based windows. Both the trend and the distribution encode the
 * same six defect classes with the same six hues, so printing the legend twice would say
 * the same thing twice and eat plot height in both panels. Instead the key sits once under
 * the instrument and drives both: muting a class removes it from the trend lines and from
 * the distribution bars at the same time, which is how an operator isolates "show me only
 * the shorts" without leaving the dashboard.
 */
export function DefectClassKey({
  hidden,
  onToggle,
  onReset,
  className,
}: {
  hidden: ReadonlySet<DefectType>;
  onToggle: (defectType: DefectType) => void;
  onReset: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  const anyHidden = hidden.size > 0;

  return (
    <div className={cn("flex flex-wrap items-center gap-x-1 gap-y-1 px-4 py-2.5", className)}>
      <span
        className="label-channel mr-3"
        title={t("dashboard.key.hint")}
      >
        {t("dashboard.key.title")}
      </span>
      {DEFECT_TYPES.map((defectType) => {
        const muted = hidden.has(defectType);
        return (
          <button
            key={defectType}
            type="button"
            aria-pressed={!muted}
            onClick={() => onToggle(defectType)}
            title={t(muted ? "dashboard.key.show" : "dashboard.key.hide", {
              label: t(`defect.${defectType}`),
            })}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[0.75rem] transition-colors hover:bg-accent",
              muted ? "text-muted-foreground/60" : "text-foreground"
            )}
          >
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-[2px] transition-opacity"
              style={{
                backgroundColor: DEFECT_TYPE_COLOR[defectType],
                opacity: muted ? 0.25 : 1,
              }}
            />
            <span className={muted ? "line-through decoration-1" : undefined}>
              {t(`defect.${defectType}`)}
            </span>
          </button>
        );
      })}
      {anyHidden ? (
        <button
          type="button"
          onClick={onReset}
          className="ml-auto rounded-md px-2 py-1 text-[0.75rem] text-brand-ink transition-colors hover:bg-accent"
        >
          {t("dashboard.key.showAll")}
        </button>
      ) : null}
    </div>
  );
}

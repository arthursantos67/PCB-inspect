"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "@/contexts/I18nContext";
import { setBoardDisposition, type BoardDisposition, type BoardDispositionDecision } from "@/lib/api-client";

type DispositionSelectorProps = {
  inspectionId: string;
  disposition: BoardDisposition | null;
};

const DECISIONS: readonly BoardDispositionDecision[] = ["approved", "rework", "discarded"];

/** Records the board's final disposition (FR-10, UC-5) — distinct from the AI's
 * `disposition_recommendation` on `Analysis`: this is the operator's own decision.
 *
 * Labelled "What happens to this board" rather than "Disposition": operators read the bare term as a verdict on the analysis
 * ("discard this analysis") when it is a verdict on the physical board, so every option names
 * the board explicitly and the field carries a one-line explanation.
 */
export function DispositionSelector({ inspectionId, disposition }: DispositionSelectorProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (decision: BoardDispositionDecision) => setBoardDisposition(inspectionId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
      queryClient.invalidateQueries({ queryKey: ["inspections", "search"] });
      queryClient.invalidateQueries({ queryKey: ["inspections", "recent"] });
    },
  });

  const current = disposition?.decision ?? null;

  return (
    // Label above the control, hint below it: this sits in the page header's action row next
    // to two badges, and a label set inline beside the select competed with the board number
    // for the eye. The hint stays visible because it is the whole point of the wording.
    <div className="field w-full sm:w-[16.5rem]">
      <label htmlFor="board-disposition">{t("boardDisposition.label")}</label>
      <select
        id="board-disposition"
        className="control"
        aria-describedby="board-disposition-hint"
        value={current ?? ""}
        disabled={mutation.isPending}
        onChange={(event) => mutation.mutate(event.target.value as BoardDispositionDecision)}
      >
        <option value="" disabled>
          {t("boardDisposition.undecided")}
        </option>
        {DECISIONS.map((decision) => (
          <option
            key={decision}
            value={decision}
            title={t(`boardDisposition.hint.${decision}`)}
          >
            {t(`boardDisposition.action.${decision}`)}
          </option>
        ))}
      </select>
      <p id="board-disposition-hint" className="text-[0.6875rem] leading-snug text-muted-foreground">
        {current ? t(`boardDisposition.hint.${current}`) : t("boardDisposition.hint")}
      </p>
    </div>
  );
}

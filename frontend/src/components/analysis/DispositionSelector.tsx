"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { setBoardDisposition, type BoardDisposition, type BoardDispositionDecision } from "@/lib/api-client";

type DispositionSelectorProps = {
  inspectionId: string;
  disposition: BoardDisposition | null;
};

const DECISION_LABEL: Record<BoardDispositionDecision, string> = {
  approved: "Approved",
  rework: "Needs rework",
  discarded: "Discarded",
};

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/** Records the board's final disposition (FR-10, UC-5) — distinct from the AI's
 * `disposition_recommendation` on `Analysis`: this is the operator's own decision.
 */
export function DispositionSelector({ inspectionId, disposition }: DispositionSelectorProps) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (decision: BoardDispositionDecision) => setBoardDisposition(inspectionId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inspections", "detail", inspectionId] });
      queryClient.invalidateQueries({ queryKey: ["inspections", "search"] });
      queryClient.invalidateQueries({ queryKey: ["inspections", "recent"] });
    },
  });

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="board-disposition" className="text-sm font-medium">
        Disposition
      </label>
      <select
        id="board-disposition"
        className={SELECT_CLASS}
        value={disposition?.decision ?? ""}
        disabled={mutation.isPending}
        onChange={(event) => mutation.mutate(event.target.value as BoardDispositionDecision)}
      >
        <option value="" disabled>
          Not set
        </option>
        {(Object.keys(DECISION_LABEL) as BoardDispositionDecision[]).map((decision) => (
          <option key={decision} value={decision}>
            {DECISION_LABEL[decision]}
          </option>
        ))}
      </select>
    </div>
  );
}

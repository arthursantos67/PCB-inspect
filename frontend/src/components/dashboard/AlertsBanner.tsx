"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  acknowledgeAlert,
  listAlerts,
  type QualityAlert,
} from "@/lib/api-client";

const ACTIVE_ALERTS_PAGE_SIZE = 50;

function describeScope(alert: QualityAlert): string {
  if (alert.type === "defect_rate_batch") {
    return `Batch ${alert.context.batch_number ?? alert.context.batch_id ?? "unknown"}`;
  }
  return `Last ${alert.context.window_minutes ?? "?"} minutes`;
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

/** Active quality alerts banner (FR-19, FE-02) — one entry per active alert (a batch and the
 * rolling time window can both be over threshold at once), each with an acknowledge action
 * (audited, FR-16). Disappears once acknowledged; refreshed live by `useEventStream`'s
 * `alert.defect_rate` invalidation (Issue 8).
 */
export function AlertsBanner() {
  const queryClient = useQueryClient();

  const alertsQuery = useQuery({
    queryKey: ["alerts", "active"],
    queryFn: () => listAlerts({ acknowledged: false, page_size: ACTIVE_ALERTS_PAGE_SIZE }),
  });

  const acknowledgeMutation = useMutation({
    mutationFn: acknowledgeAlert,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const alerts = alertsQuery.data?.results ?? [];
  if (alerts.length === 0) return null;

  return (
    <div className="flex flex-col gap-2" role="alert" aria-live="polite">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm"
        >
          <span className="text-destructive">
            <span className="font-medium">Quality alert:</span> {describeScope(alert)} defect
            rate is {formatRate(alert.context.observed_rate)}, above the{" "}
            {formatRate(alert.context.threshold)} threshold.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={acknowledgeMutation.isPending}
            onClick={() => acknowledgeMutation.mutate(alert.id)}
          >
            Acknowledge
          </Button>
        </div>
      ))}
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import {
  acknowledgeAlert,
  listAlerts,
  type QualityAlert,
} from "@/lib/api-client";

const ACTIVE_ALERTS_PAGE_SIZE = 50;

function describeScope(alert: QualityAlert, t: Translate): string {
  if (alert.type === "defect_rate_batch") {
    return t("alerts.batchScope", {
      batch: alert.context.batch_number ?? alert.context.batch_id ?? t("alerts.unknownBatch"),
    });
  }
  return t("alerts.windowScope", { minutes: alert.context.window_minutes ?? "?" });
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
  const { t } = useI18n();

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
          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 overflow-hidden rounded-lg border border-border bg-card py-2.5 pr-3 pl-4 shadow-panel"
          style={{
            // A solid rule of the critical color down the leading edge instead of a wash
            // across the whole row: the alert is unmistakable without turning a panel of
            // readable text pink.
            boxShadow: "inset 3px 0 0 var(--status-critical)",
          }}
        >
          <span className="flex min-w-0 items-center gap-2.5">
            <TriangleAlert
              aria-hidden="true"
              className="size-4 shrink-0 text-status-critical"
            />
            <span className="text-[0.8125rem] leading-relaxed">
              <span className="font-semibold">{t("alerts.title")}</span>{" "}
              {t("alerts.body", {
                scope: describeScope(alert, t),
                observed: formatRate(alert.context.observed_rate),
                threshold: formatRate(alert.context.threshold),
              })}
            </span>
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={acknowledgeMutation.isPending}
            onClick={() => acknowledgeMutation.mutate(alert.id)}
          >
            {t("alerts.acknowledge")}
          </Button>
        </div>
      ))}
    </div>
  );
}

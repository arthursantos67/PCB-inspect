"use client";

import { useRouter } from "next/navigation";

import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useI18n } from "@/contexts/I18nContext";
import type { RecentBatch } from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

/** Recently-analyzed-batches table — replaces the old
 * per-board "Recent analyses" list on the dashboard with one row per batch. Clicking a row
 * opens the inspections list filtered to that batch, same navigation target `/inspections`
 * already supports via `batch_number` (FR-07).
 */
export function RecentBatchesTable({
  items,
  isLoading,
  isError,
}: {
  items: RecentBatch[];
  isLoading: boolean;
  isError?: boolean;
}) {
  const router = useRouter();
  const { t } = useI18n();

  if (!isLoading && items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {isError ? t("batches.loadFailed") : t("batches.empty")}
      </p>
    );
  }

  return (
    <Table aria-busy={isLoading}>
      <TableHeader>
        <TableRow>
          <TableHead>{t("batches.column.batch")}</TableHead>
          <TableHead>{t("batches.column.defects")}</TableHead>
          <TableHead>{t("batches.column.severity")}</TableHead>
          <TableHead>{t("batches.column.status")}</TableHead>
          <TableHead>{t("batches.column.date")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow
            key={item.batch_id}
            className="cursor-pointer"
            onClick={() =>
              router.push(`/inspections?batch_number=${encodeURIComponent(item.batch_number)}`)
            }
          >
            <TableCell className="font-medium">{item.batch_number}</TableCell>
            <TableCell className="tabular-nums">{item.defect_count}</TableCell>
            <TableCell>
              {item.severity ? (
                <SeverityBadge severity={item.severity} />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell>
              <StatusBadge status={item.status} />
            </TableCell>
            <TableCell className="text-muted-foreground">{formatTimestamp(item.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

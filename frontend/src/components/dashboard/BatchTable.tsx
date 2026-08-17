"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useI18n } from "@/contexts/I18nContext";
import type { BatchListItem } from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

/** The batch-first inspections list. Boards arrive in
 * batches, so the list starts at that level and a row opens the batch's own boards; the
 * per-board table (`InspectionTable`) is unchanged and is what the drill-down renders.
 */
export function BatchTable({
  items,
  isLoading,
  isError,
  emptyMessage,
}: {
  items: BatchListItem[];
  isLoading: boolean;
  isError?: boolean;
  emptyMessage?: string;
}) {
  const router = useRouter();
  const { t } = useI18n();

  if (!isLoading && items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {isError ? t("batches.loadFailed") : (emptyMessage ?? t("batchTable.empty"))}
      </p>
    );
  }

  return (
    <Table aria-busy={isLoading}>
      <TableHeader>
        <TableRow>
          <TableHead>{t("batchTable.column.batch")}</TableHead>
          <TableHead>{t("batchTable.column.boards")}</TableHead>
          <TableHead>{t("batchTable.column.withDefects")}</TableHead>
          <TableHead>{t("batchTable.column.defects")}</TableHead>
          <TableHead>{t("batchTable.column.defectTypes")}</TableHead>
          <TableHead>{t("batchTable.column.severity")}</TableHead>
          <TableHead>{t("batchTable.column.status")}</TableHead>
          <TableHead>{t("batchTable.column.lastActivity")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => {
          const href = `/inspections?batch_number=${encodeURIComponent(item.batch_number)}`;
          return (
            <TableRow
              key={item.batch_id}
              className="cursor-pointer"
              onClick={() => router.push(href)}
            >
              <TableCell className="font-medium">
                <Link href={href} className="hover:underline focus-visible:underline">
                  {item.batch_number}
                </Link>
              </TableCell>
              <TableCell className="tabular-nums">
                {item.completed_count}
                {item.completed_count !== item.board_count && (
                  <span className="text-muted-foreground">
                    {" "}
                    {t("common.ofTotal", { total: item.board_count })}
                  </span>
                )}
              </TableCell>
              <TableCell className="tabular-nums">
                {item.boards_with_defects}
                <span className="text-muted-foreground">
                  {" "}
                  ({Math.round(item.defect_rate * 100)}%)
                </span>
              </TableCell>
              <TableCell className="tabular-nums">{item.defect_count}</TableCell>
              <TableCell>
                {item.defect_types.length === 0 ? (
                  <span className="text-muted-foreground">{t("common.none")}</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {item.defect_types.map(({ defect_type, count }) => (
                      <DefectBadge key={defect_type} defectType={defect_type} count={count} />
                    ))}
                  </div>
                )}
              </TableCell>
              <TableCell>
                {item.severity ? (
                  <SeverityBadge severity={item.severity} />
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </TableCell>
              <TableCell>
                <StatusBadge status={item.status} />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatTimestamp(item.last_activity_at)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

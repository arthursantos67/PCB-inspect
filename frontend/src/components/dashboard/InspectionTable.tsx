"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useI18n } from "@/contexts/I18nContext";
import type { InspectionListItem } from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

/** Recent-analyses table (FE-02/FE-04) — reused as-is between the dashboard and (later)
 * search/history screen, per PRD section 12.2.
 */
export function InspectionTable({
  items,
  isLoading,
  isError,
  emptyMessage,
}: {
  items: InspectionListItem[];
  isLoading: boolean;
  isError?: boolean;
  emptyMessage?: string;
}) {
  const router = useRouter();
  const { t } = useI18n();

  if (!isLoading && items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {isError ? t("inspectionTable.loadFailed") : (emptyMessage ?? t("inspectionTable.empty"))}
      </p>
    );
  }

  return (
    <Table aria-busy={isLoading}>
      <TableHeader>
        <TableRow>
          <TableHead>{t("inspectionTable.column.board")}</TableHead>
          <TableHead>{t("inspectionTable.column.batch")}</TableHead>
          <TableHead>{t("inspectionTable.column.defects")}</TableHead>
          <TableHead>{t("inspectionTable.column.severity")}</TableHead>
          <TableHead>{t("inspectionTable.column.status")}</TableHead>
          <TableHead>{t("inspectionTable.column.disposition")}</TableHead>
          <TableHead>{t("inspectionTable.column.created")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow
            key={item.id}
            className="cursor-pointer"
            onClick={() => router.push(`/inspections/${item.id}`)}
          >
            <TableCell className="font-medium">
              <Link href={`/inspections/${item.id}`} className="hover:underline focus-visible:underline">
                {item.board_number ?? "—"}
              </Link>
            </TableCell>
            <TableCell className="text-muted-foreground">{item.batch_number ?? "—"}</TableCell>
            <TableCell>
              {item.defect_types.length === 0 ? (
                <span className="text-muted-foreground">{t("common.none")}</span>
              ) : (
                <div className="flex flex-wrap gap-1">
                  {item.defect_types.map((defectType) => (
                    <DefectBadge key={defectType} defectType={defectType} />
                  ))}
                </div>
              )}
            </TableCell>
            <TableCell>
              {item.severity_max ? (
                <SeverityBadge severity={item.severity_max} />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell>
              <StatusBadge status={item.status} />
            </TableCell>
            <TableCell className="text-muted-foreground">
              {item.disposition ? t(`disposition.${item.disposition}`) : "—"}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatTimestamp(item.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { InspectionListItem } from "@/lib/api-client";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Recent-analyses table (FE-02/FE-04) — reused as-is between the dashboard and (later)
 * search/history screen, per PRD section 12.2.
 */
export function InspectionTable({
  items,
  isLoading,
  isError,
}: {
  items: InspectionListItem[];
  isLoading: boolean;
  isError?: boolean;
}) {
  if (!isLoading && items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {isError ? "Failed to load inspections." : "No inspections yet."}
      </p>
    );
  }

  return (
    <Table aria-busy={isLoading}>
      <TableHeader>
        <TableRow>
          <TableHead>Board</TableHead>
          <TableHead>Batch</TableHead>
          <TableHead>Defects</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id}>
            <TableCell className="font-medium">{item.board_number ?? "—"}</TableCell>
            <TableCell className="text-muted-foreground">{item.batch_number ?? "—"}</TableCell>
            <TableCell>
              {item.defect_types.length === 0 ? (
                <span className="text-muted-foreground">None</span>
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
              {formatDateTime(item.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

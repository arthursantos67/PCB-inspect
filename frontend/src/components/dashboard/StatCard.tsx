import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Dashboard metric tile (FE-02) — a single labeled hero number, per the dataviz skill's
 * stat-tile form (a headline value doesn't need to be a chart).
 */
export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tabular-nums">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

export function StatCardSkeleton({ label }: { label: string }) {
  return (
    <Card>
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className="h-9 w-16 animate-pulse rounded-md bg-muted"
          role="status"
          aria-label={`Loading ${label}`}
        />
      </CardContent>
    </Card>
  );
}

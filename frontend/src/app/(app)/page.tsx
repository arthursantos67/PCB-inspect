import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Dashboard</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Scaffolding placeholder — stat cards, defect trends, and recent inspections land with
        FE-02.
      </CardContent>
    </Card>
  );
}

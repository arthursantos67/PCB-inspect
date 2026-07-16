"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AnnotatedImageViewer } from "@/components/viewer/AnnotatedImageViewer";
import { DetectionsPanel } from "@/components/viewer/DetectionsPanel";
import { useAuthenticatedImage } from "@/hooks/useAuthenticatedImage";
import { createChatSession, getInspection, type ImageStatus } from "@/lib/api-client";

const PROCESSING_STEPS: { key: ImageStatus; label: string }[] = [
  { key: "QUEUED", label: "Queued" },
  { key: "PROCESSING", label: "Detecting" },
  { key: "DETECTED", label: "Detected" },
  { key: "ANALYZING", label: "Analyzing" },
  { key: "COMPLETED", label: "Completed" },
];

function ProcessingStepper({ status }: { status: ImageStatus }) {
  const currentIndex = PROCESSING_STEPS.findIndex((step) => step.key === status);
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Processing progress">
      {PROCESSING_STEPS.map((step, index) => {
        const isCurrent = index === currentIndex;
        const isDone = currentIndex >= 0 && index < currentIndex;
        return (
          <li
            key={step.key}
            aria-current={isCurrent ? "step" : undefined}
            className={`rounded-full border px-2.5 py-1 text-xs font-medium ${
              isCurrent
                ? "border-primary bg-primary text-primary-foreground"
                : isDone
                  ? "border-border bg-muted text-foreground"
                  : "border-border text-muted-foreground"
            }`}
          >
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function InspectionDetailPage() {
  const params = useParams<{ id: string }>();
  const inspectionId = params.id;
  const router = useRouter();
  const [hoveredDetectionId, setHoveredDetectionId] = useState<string | null>(null);

  // Query key prefixed with "inspections" — useEventStream (FE-09) already invalidates that
  // prefix on every SSE pipeline event (Issue 8), so this refetches live with no extra wiring.
  const detailQuery = useQuery({
    queryKey: ["inspections", "detail", inspectionId],
    queryFn: () => getInspection(inspectionId),
  });

  // FE-03's "Ask about this analysis" entry point: opens a new chat session pre-scoped to
  // this inspection's analysis, so the operator never has to re-type which board they mean.
  const askAboutAnalysis = useMutation({
    mutationFn: (analysisId: string) => createChatSession(analysisId),
    onSuccess: (session) => router.push(`/chat/${session.id}`),
  });

  const detail = detailQuery.data;
  const annotatedAvailable = (detail?.detections.length ?? 0) > 0;

  const originalImage = useAuthenticatedImage(inspectionId, "original", { enabled: !!detail });
  const annotatedImage = useAuthenticatedImage(inspectionId, "annotated", { enabled: annotatedAvailable });

  if (detailQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading inspection…</p>;
  }

  if (detailQuery.isError || !detail) {
    return <p className="text-sm text-destructive">Failed to load this inspection.</p>;
  }

  const analysis = detail.analysis;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Board {detail.board.board_number ?? "—"}</h1>
          <p className="text-sm text-muted-foreground">Batch {detail.board.batch_number ?? "—"}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={detail.status} />
          {analysis?.severity_max && <SeverityBadge severity={analysis.severity_max} />}
        </div>
      </div>

      {detail.status === "FAILED" ? (
        <Card>
          <CardHeader>
            <CardTitle>Processing failed</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-destructive">{detail.failure_reason ?? "Unknown error."}</p>
          </CardContent>
        </Card>
      ) : detail.status !== "COMPLETED" ? (
        <Card>
          <CardHeader>
            <CardTitle>Processing</CardTitle>
          </CardHeader>
          <CardContent>
            <ProcessingStepper status={detail.status} />
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Image</CardTitle>
          </CardHeader>
          <CardContent>
            <AnnotatedImageViewer
              originalUrl={originalImage.url}
              annotatedUrl={annotatedImage.url}
              annotatedAvailable={annotatedAvailable}
              detections={detail.detections}
              hoveredDetectionId={hoveredDetectionId}
              onHoverDetection={setHoveredDetectionId}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Detections</CardTitle>
          </CardHeader>
          <CardContent>
            <DetectionsPanel
              detections={detail.detections}
              hoveredDetectionId={hoveredDetectionId}
              onHoverDetection={setHoveredDetectionId}
            />
          </CardContent>
        </Card>
      </div>

      {analysis && (
        <Card>
          <CardHeader>
            <CardTitle>Analysis</CardTitle>
            <CardAction>
              <Button
                size="sm"
                variant="outline"
                onClick={() => askAboutAnalysis.mutate(analysis.id)}
                disabled={askAboutAnalysis.isPending}
              >
                Ask about this analysis
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {analysis.executive_summary && <p className="text-sm">{analysis.executive_summary}</p>}
            <div className="flex flex-col gap-3">
              {(analysis.per_defect ?? []).map((entry) => (
                <div key={entry.detection_id} className="rounded-lg border border-border p-3">
                  <div className="mb-2">
                    <SeverityBadge severity={entry.severity} />
                  </div>
                  <p className="text-sm">{entry.description}</p>
                  {entry.probable_causes.length > 0 && (
                    <p className="mt-2 text-sm">
                      <span className="font-medium">Probable causes: </span>
                      {entry.probable_causes.join("; ")}
                    </p>
                  )}
                  {entry.suggested_solutions.length > 0 && (
                    <p className="mt-1 text-sm">
                      <span className="font-medium">Suggested solutions: </span>
                      {entry.suggested_solutions.join("; ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Metadata</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{formatDateTime(detail.created_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Processed</dt>
              <dd>{detail.processed_at ? formatDateTime(detail.processed_at) : "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Processing duration</dt>
              <dd>{detail.duration_ms !== null ? `${(detail.duration_ms / 1000).toFixed(1)}s` : "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Model version</dt>
              <dd>{detail.detections[0]?.model_version ?? "—"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

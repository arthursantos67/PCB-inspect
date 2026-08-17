"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { DispositionSelector } from "@/components/analysis/DispositionSelector";
import { PageHeader } from "@/components/layout/PageHeader";
import { ReviewPanel } from "@/components/analysis/ReviewPanel";
import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { IMAGE_STATUSES, StatusBadge } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AnnotatedImageViewer } from "@/components/viewer/AnnotatedImageViewer";
import { DetectionsPanel } from "@/components/viewer/DetectionsPanel";
import { useI18n } from "@/contexts/I18nContext";
import { useAuthenticatedImage } from "@/hooks/useAuthenticatedImage";
import { createChatSession, getInspection, type BBox, type ImageStatus } from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

// Same wording as the status badge and the status filter, so
// the stepper here and the badge in the list never name the same stage differently — both read
// the `status.` keys out of the dictionaries.
const PROCESSING_STEPS: readonly ImageStatus[] = IMAGE_STATUSES.filter(
  (status) => status !== "FAILED",
);

function ProcessingStepper({ status }: { status: ImageStatus }) {
  const { t } = useI18n();
  const currentIndex = PROCESSING_STEPS.indexOf(status);
  return (
    // A track, not a row of pills: the completed run is drawn as a filled rule behind the
    // steps, so how far along the board is reads before any label does.
    <ol
      className="flex flex-wrap items-stretch gap-x-1 gap-y-3"
      aria-label={t("detail.processingProgress")}
    >
      {PROCESSING_STEPS.map((step, index) => {
        const isCurrent = index === currentIndex;
        const isDone = currentIndex >= 0 && index < currentIndex;
        return (
          <li
            key={step}
            aria-current={isCurrent ? "step" : undefined}
            className="flex min-w-[7.5rem] flex-1 flex-col gap-2"
          >
            <span
              aria-hidden="true"
              className={`h-[3px] rounded-full transition-colors ${
                isCurrent ? "bg-brand" : isDone ? "bg-foreground/35" : "bg-border"
              }`}
            />
            <span
              className={`text-[0.75rem] leading-tight ${
                isCurrent
                  ? "font-medium text-foreground"
                  : isDone
                    ? "text-muted-foreground"
                    : "text-muted-foreground/60"
              }`}
            >
              {t(`status.${step}`)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** A board can sit in the queue for hours on a single-GPU station, and "40196.0s" is not a
 * duration anyone reads. Seconds up to a minute, then minutes, then hours and minutes.
 */
function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
}

/** Which of the nine zones a detection's centre falls into, from its (normalized) box. Used to
 * caption each analysis passage so the text can be matched to a
 * box on the image without counting rows.
 *
 * The thirds and the zone keys are the backend's (`app.agents.prompts.v1.position_zone`), so
 * this caption and the one in the PDF describe the same defect the same way.
 */
function positionZone({ x1, y1, x2, y2 }: BBox): PositionZone {
  const centreX = (x1 + x2) / 2;
  const centreY = (y1 + y2) / 2;
  const horizontal = centreX < 1 / 3 ? "left" : centreX > 2 / 3 ? "right" : "centre";
  const vertical = centreY < 1 / 3 ? "upper" : centreY > 2 / 3 ? "lower" : "middle";
  if (horizontal === "centre" && vertical === "middle") return "centre";
  return `${vertical}_${horizontal}` as PositionZone;
}

type PositionZone =
  | "centre"
  | "upper_left"
  | "upper_centre"
  | "upper_right"
  | "middle_left"
  | "middle_right"
  | "lower_left"
  | "lower_centre"
  | "lower_right";

export default function InspectionDetailPage() {
  const params = useParams<{ id: string }>();
  const inspectionId = params.id;
  const router = useRouter();
  const { language, t } = useI18n();
  const [hoveredDetectionId, setHoveredDetectionId] = useState<string | null>(null);

  // Query key prefixed with "inspections" — useEventStream (FE-09) already invalidates that
  // prefix on every SSE pipeline event (Issue 8), so this refetches live with no extra wiring.
  // That is also what makes a switched language land: the API answers with the analysis it can
  // localize for free and queues the translation, whose `analysis.translated` event invalidates
  // this key again once the text is cached.
  const detailQuery = useQuery({
    queryKey: ["inspections", "detail", inspectionId, language],
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

  const originalImage = useAuthenticatedImage(inspectionId, "original", {
    enabled: !!detail,
  });
  const annotatedImage = useAuthenticatedImage(inspectionId, "annotated", {
    enabled: annotatedAvailable,
  });

  if (detailQuery.isPending) {
    return <p className="text-sm text-muted-foreground">{t("detail.loading")}</p>;
  }

  if (detailQuery.isError || !detail) {
    return <p className="text-sm text-destructive">{t("detail.loadFailed")}</p>;
  }

  const analysis = detail.analysis;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t("detail.eyebrowBatch", { batch: detail.board.batch_number ?? "—" })}
        // The board number is the string an operator matches against the label on the physical
        // board in their hand, so it is set in the identifier face.
        title={
          <span className="flex items-baseline gap-2">
            <span className="text-muted-foreground">{t("detail.board")}</span>
            <span className="ident text-[1.375rem] font-semibold">
              {detail.board.board_number ?? "—"}
            </span>
          </span>
        }
        actions={
          <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
            <div className="flex items-center gap-2 pb-1.5">
              <StatusBadge status={detail.status} />
              {analysis?.severity_max && <SeverityBadge severity={analysis.severity_max} />}
            </div>
            <DispositionSelector inspectionId={inspectionId} disposition={detail.disposition} />
          </div>
        }
      >
        <Link
          href="/inspections"
          className="inline-flex w-fit items-center gap-1.5 text-[0.8125rem] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          {t("detail.allInspections")}
        </Link>
      </PageHeader>

      {detail.status === "FAILED" ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("detail.processingFailed")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-destructive">
              {detail.failure_reason ?? t("detail.unknownError")}
            </p>
          </CardContent>
        </Card>
      ) : detail.status !== "COMPLETED" ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("detail.processing")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ProcessingStepper status={detail.status} />
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("detail.image")}</CardTitle>
          </CardHeader>
          <CardContent>
            <AnnotatedImageViewer
              inspectionId={inspectionId}
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
            <CardTitle>{t("detail.detections")}</CardTitle>
          </CardHeader>
          <CardContent>
            <DetectionsPanel
              inspectionId={inspectionId}
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
            <CardTitle>{t("detail.analysis")}</CardTitle>
            <CardAction>
              <Button
                size="sm"
                variant="outline"
                onClick={() => askAboutAnalysis.mutate(analysis.id)}
                disabled={askAboutAnalysis.isPending}
              >
                {t("detail.ask")}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {/* The summary is the one thing an operator reads before deciding whether to read
                anything else, so it is set as a lead paragraph with a copper rule beside it. */}
            {analysis.executive_summary && (
              <p className="border-l-2 border-brand pl-4 text-[0.9375rem] leading-relaxed">
                {analysis.executive_summary}
              </p>
            )}
            {/* Each passage is captioned with the detection it is about: same number as the
                detections list and the boxes on the image, plus class, confidence and where on
                the board it sits. Hovering a passage lights up
                its box, so "which one is this about" is answerable at a glance. */}
            <div className="flex flex-col gap-3">
              {(analysis.per_defect ?? [])
                .map((entry) => ({
                  entry,
                  index: detail.detections.findIndex((d) => d.id === entry.detection_id),
                }))
                // Read in the same order as the detections list and the numbers on the image.
                // The agent returns these ranked by confidence, which made the page count
                // 2, 5, 3, 4, 1, 6 down the column while the panel beside it counted 1 to 6.
                .sort((a, b) => (a.index < 0 ? 1 : b.index < 0 ? -1 : a.index - b.index))
                .map(({ entry, index }) => {
                  const detection = index >= 0 ? detail.detections[index] : null;
                  return (
                    <div
                      key={entry.detection_id}
                      className={`rounded-lg border p-4 transition-colors ${
                        detection && hoveredDetectionId === detection.id
                          ? "border-brand bg-accent"
                          : "border-border"
                      }`}
                      onMouseEnter={() => detection && setHoveredDetectionId(detection.id)}
                      onMouseLeave={() => detection && setHoveredDetectionId(null)}
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        {detection ? (
                          <>
                            <span className="readout flex size-5 shrink-0 items-center justify-center rounded-[4px] border border-border bg-card text-[0.6875rem] font-semibold">
                              {index + 1}
                            </span>
                            <DefectBadge defectType={detection.defect_type} />
                            <span className="text-[0.75rem] text-muted-foreground">
                              {detection.source === "manual"
                                ? t("detail.manuallyAnnotated")
                                : t("detail.confidence", {
                                    value: (Number(detection.confidence) * 100).toFixed(1),
                                  })}
                              {", "}
                              {t(`position.${positionZone(detection.bbox)}`)}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {t("detail.detectionGone")}
                          </span>
                        )}
                        <SeverityBadge severity={entry.severity} />
                      </div>
                      <p className="text-sm">{entry.description}</p>
                      {entry.probable_causes.length > 0 && (
                        <p className="mt-2 text-sm">
                          <span className="font-medium">{t("detail.probableCauses")}</span>
                          {entry.probable_causes.join("; ")}
                        </p>
                      )}
                      {entry.suggested_solutions.length > 0 && (
                        <p className="mt-1 text-sm">
                          <span className="font-medium">{t("detail.suggestedSolutions")}</span>
                          {entry.suggested_solutions.join("; ")}
                        </p>
                      )}
                    </div>
                  );
                })}
            </div>
            <ReviewPanel
              inspectionId={inspectionId}
              analysisId={analysis.id}
              reviewStatus={analysis.review_status}
              reviews={analysis.reviews}
            />
          </CardContent>
        </Card>
      )}

      {/* Provenance, not content: a seamed readout strip rather than a card, so it closes the
          page as a plate on the bench instead of competing with the analysis above it. */}
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border shadow-panel sm:grid-cols-4">
        {[
          { label: t("detail.meta.created"), value: formatTimestamp(detail.created_at) },
          {
            label: t("detail.meta.processed"),
            value: detail.processed_at ? formatTimestamp(detail.processed_at) : "—",
          },
          {
            label: t("detail.meta.duration"),
            value: detail.duration_ms !== null ? formatDuration(detail.duration_ms) : "—",
          },
          {
            label: t("detail.meta.modelVersion"),
            value: detail.detections.find((d) => d.model_version)?.model_version ?? "—",
          },
        ].map((cell) => (
          <div key={cell.label} className="bg-card px-4 py-3">
            <dt className="label-channel">{cell.label}</dt>
            <dd className="readout mt-1.5 text-[0.8125rem]">{cell.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

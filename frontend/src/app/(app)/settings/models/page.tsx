"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LampChip, type LampTone } from "@/components/ui/lamp-chip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/contexts/I18nContext";
import {
  activateModelVersion,
  ApiError,
  listModelVersions,
  uploadModelWeights,
  type ModelEvaluationStatus,
  type ModelVersion,
} from "@/lib/api-client";
import { DEFECT_TYPES, type DefectType } from "@/lib/chart-colors";
import { formatTimestamp } from "@/lib/format";

// Mirrors app.settings.models_service.MAP50_FLOOR (NFR-05) — display-only; the backend is
// the source of truth and enforces this regardless of what the client shows.
const MAP50_FLOOR = 0.95;

/** Evaluation is a job with a lifecycle, so it wears the same lamp as every other job state
 * in the app: unlit while queued, pulsing while it runs, green when it clears, red when it
 * does not.
 */
const STATUS_LAMP: Record<
  ModelEvaluationStatus,
  { tone: LampTone; pulse?: boolean; hollow?: boolean }
> = {
  PENDING: { tone: "neutral", hollow: true },
  RUNNING: { tone: "neutral", pulse: true },
  COMPLETED: { tone: "good" },
  FAILED: { tone: "critical" },
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function ActivateControl({
  modelVersion,
  onActivated,
}: {
  modelVersion: ModelVersion;
  onActivated: () => void;
}) {
  const { t } = useI18n();
  const [overriding, setOverriding] = useState(false);
  const [justification, setJustification] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const belowFloor = modelVersion.metrics !== null && modelVersion.metrics.map50 < MAP50_FLOOR;

  async function activate(override: boolean) {
    setBusy(true);
    setError(null);
    try {
      await activateModelVersion(modelVersion.id, {
        override,
        justification: override ? justification : undefined,
      });
      setOverriding(false);
      setJustification("");
      onActivated();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MODEL_ACTIVATION_FAILED" && belowFloor) {
        setOverriding(true);
      }
      setError(err instanceof ApiError ? err.message : t("models.activateFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (modelVersion.is_active) {
    return <LampChip tone="good">{t("models.inProduction")}</LampChip>;
  }

  if (modelVersion.evaluation_status !== "COMPLETED") {
    return <span className="text-xs text-muted-foreground">{t("models.waitingEvaluation")}</span>;
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {!overriding && (
        <Button size="sm" variant="brand" disabled={busy} onClick={() => void activate(false)}>
          {t("models.activate")}
        </Button>
      )}
      {overriding && (
        <div className="flex w-full max-w-xs flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2">
          <p className="text-xs text-destructive">
            {t("models.overrideWarning", { floor: formatPercent(MAP50_FLOOR) })}
          </p>
          <textarea
            className="min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            placeholder={t("models.overridePlaceholder")}
            value={justification}
            onChange={(event) => setJustification(event.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={busy || !justification.trim()}
              onClick={() => void activate(true)}
            >
              {t("models.activateOverride")}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOverriding(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}
      {error && <p className="max-w-xs text-xs text-destructive">{error}</p>}
    </div>
  );
}

function MetricsCell({ modelVersion }: { modelVersion: ModelVersion }) {
  const { t } = useI18n();
  if (!modelVersion.metrics) return <span className="text-muted-foreground">—</span>;
  const { map50, map50_95, per_class } = modelVersion.metrics;

  return (
    <details className="text-xs">
      <summary className="cursor-pointer whitespace-nowrap">
        mAP@50 {formatPercent(map50)} · mAP@50-95 {formatPercent(map50_95)}
      </summary>
      <ul className="mt-1 flex flex-col gap-0.5 text-muted-foreground">
        {Object.entries(per_class).map(([defectType, ap]) => (
          <li key={defectType}>
            {/* A per-class key the model reports but this build doesn't know shows raw,
                rather than as a missing-translation key. */}
            {DEFECT_TYPES.includes(defectType as DefectType)
              ? t(`defect.${defectType as DefectType}`)
              : defectType}
            : {formatPercent(ap)}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Derives a first-guess version name from the uploaded file's name, so the common case
 * (`best.pt` straight out of the notebook, or `pcb-v2.pt`) needs no typing at all. `best` is
 * everyone's filename and says nothing, so it becomes a dated name instead of a collision.
 */
function suggestVersionName(fileName: string): string {
  const stem = fileName.replace(/\.pt$/i, "").replace(/[^A-Za-z0-9._-]+/g, "-");
  const today = new Date().toISOString().slice(0, 10);
  if (!stem || /^best$/i.test(stem)) return `best-${today}`;
  return stem;
}

function UploadWeightsCard({ onUploaded }: { onUploaded: () => void }) {
  const { t } = useI18n();
  const [version, setVersion] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(selected: File | null) {
    setFile(selected);
    setUploaded(null);
    setError(null);
    if (selected && !version.trim()) setVersion(suggestVersionName(selected.name));
  }

  async function handleUpload() {
    if (!file) return;
    setError(null);
    setUploaded(null);
    setUploading(true);
    try {
      const created = await uploadModelWeights({ version: version.trim(), file });
      setVersion("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setUploaded(created.version);
      onUploaded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("models.upload.failed"));
    } finally {
      setUploading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("models.upload.title")}</CardTitle>
        <CardDescription>
          {t("models.upload.descriptionStart")}
          <code>best.pt</code>
          {t("models.upload.descriptionRest")}
          <Link className="underline" href="/model">
            {t("models.upload.descriptionLink")}
          </Link>
          {t("models.upload.descriptionEnd")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid max-w-xl grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-weights-file">{t("models.upload.file")}</Label>
            <Input
              id="model-weights-file"
              ref={fileInputRef}
              type="file"
              accept=".pt"
              // The native file button renders as bare text next to a styled text field, which
              // reads as a broken control. Dressed as the outline button it actually is.
              className="text-xs file:mr-3 file:h-7 file:rounded-[5px] file:border file:border-border-strong file:bg-card file:px-2.5 file:text-xs file:font-medium file:text-foreground"
              onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-version">{t("models.upload.version")}</Label>
            <Input
              id="model-version"
              placeholder="v1.1.0"
              value={version}
              onChange={(event) => setVersion(event.target.value)}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="brand"
            size="sm"
            className="w-fit"
            disabled={uploading || !file || !version.trim()}
            aria-busy={uploading}
            onClick={() => void handleUpload()}
          >
            {uploading ? t("models.upload.uploading") : t("models.upload.submit")}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <p aria-live="polite" className="text-xs text-muted-foreground">
          {uploading
            ? t("models.upload.inProgress")
            : uploaded
              ? t("models.upload.done", { version: uploaded })
              : ""}
        </p>
      </CardContent>
    </Card>
  );
}

export default function SettingsModelsPage() {
  const { t } = useI18n();
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setVersions(await listModelVersions());
      setLoadError(null);
    } catch (err) {
      // The empty string stands for "failed, with nothing specific to say": the generic
      // wording is picked at render time so this callback stays independent of the language
      // and the polling effect below is not restarted by a language switch.
      setLoadError(err instanceof ApiError ? err.message : "");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Golden-set evaluation runs asynchronously (FR-12) — poll while any version is still
  // pending/running so status/results show up without a manual refresh.
  useEffect(() => {
    const hasPending = versions.some(
      (v) => v.evaluation_status === "PENDING" || v.evaluation_status === "RUNNING"
    );
    if (!hasPending) return;
    const interval = setInterval(() => void refresh(), 3000);
    return () => clearInterval(interval);
  }, [versions, refresh]);

  return (
    <div className="flex flex-col gap-6">
      {loadError !== null && (
        <p className="text-sm text-destructive">{loadError || t("models.loadFailed")}</p>
      )}

      <UploadWeightsCard onUploaded={() => void refresh()} />

      <Card>
        <CardHeader>
          <CardTitle>{t("models.versions.title")}</CardTitle>
          <CardDescription>{t("models.versions.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("models.column.version")}</TableHead>
                <TableHead>{t("models.column.evaluation")}</TableHead>
                <TableHead>{t("models.column.metrics")}</TableHead>
                <TableHead>{t("models.column.registered")}</TableHead>
                <TableHead>{t("models.column.activation")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.map((modelVersion) => (
                <TableRow key={modelVersion.id}>
                  <TableCell className="font-medium">{modelVersion.version}</TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <LampChip {...STATUS_LAMP[modelVersion.evaluation_status]}>
                        {t(`models.status.${modelVersion.evaluation_status}`)}
                      </LampChip>
                      {modelVersion.evaluation_status === "FAILED" &&
                        modelVersion.evaluation_error && (
                          <span className="max-w-64 text-xs text-destructive">
                            {modelVersion.evaluation_error}
                          </span>
                        )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <MetricsCell modelVersion={modelVersion} />
                  </TableCell>
                  <TableCell className="readout text-xs whitespace-nowrap text-muted-foreground">
                    {formatTimestamp(modelVersion.created_at)}
                  </TableCell>
                  <TableCell>
                    <ActivateControl
                      modelVersion={modelVersion}
                      onActivated={() => void refresh()}
                    />
                  </TableCell>
                </TableRow>
              ))}
              {versions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    {t("models.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  activateModelVersion,
  ApiError,
  listModelVersions,
  registerModelVersion,
  type ModelEvaluationStatus,
  type ModelVersion,
} from "@/lib/api-client";
import { DEFECT_TYPE_LABEL, type DefectType } from "@/lib/chart-colors";

// Mirrors app.settings.models_service.MAP50_FLOOR (NFR-05) — display-only; the backend is
// the source of truth and enforces this regardless of what the client shows.
const MAP50_FLOOR = 0.95;

const STATUS_LABEL: Record<ModelEvaluationStatus, string> = {
  PENDING: "Evaluation pending",
  RUNNING: "Evaluating…",
  COMPLETED: "Evaluated",
  FAILED: "Evaluation failed",
};

const STATUS_VARIANT: Record<
  ModelEvaluationStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  PENDING: "outline",
  RUNNING: "secondary",
  COMPLETED: "default",
  FAILED: "destructive",
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
      setError(err instanceof ApiError ? err.message : "Failed to activate this version.");
    } finally {
      setBusy(false);
    }
  }

  if (modelVersion.is_active) {
    return <Badge>Active</Badge>;
  }

  if (modelVersion.evaluation_status !== "COMPLETED") {
    return <span className="text-xs text-muted-foreground">Waiting on evaluation</span>;
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {!overriding && (
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void activate(false)}>
          Activate
        </Button>
      )}
      {overriding && (
        <div className="flex w-full max-w-xs flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2">
          <p className="text-xs text-destructive">
            mAP@50 is below the {formatPercent(MAP50_FLOOR)} floor (NFR-05). Activating anyway
            requires a justification and is recorded in the audit trail (FR-16).
          </p>
          <textarea
            className="min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            placeholder="Why activate below the floor?"
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
              Activate with override
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOverriding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {error && <p className="max-w-xs text-xs text-destructive">{error}</p>}
    </div>
  );
}

function MetricsCell({ modelVersion }: { modelVersion: ModelVersion }) {
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
            {DEFECT_TYPE_LABEL[defectType as DefectType] ?? defectType}: {formatPercent(ap)}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function SettingsModelsPage() {
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [version, setVersion] = useState("");
  const [weightsPath, setWeightsPath] = useState("");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setVersions(await listModelVersions());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Failed to load model versions.");
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

  async function handleRegister() {
    setRegisterError(null);
    setRegistering(true);
    try {
      await registerModelVersion({ version, weights_path: weightsPath });
      setVersion("");
      setWeightsPath("");
      await refresh();
    } catch (err) {
      setRegisterError(
        err instanceof ApiError ? err.message : "Failed to register this version."
      );
    } finally {
      setRegistering(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Register a new version</CardTitle>
          <CardDescription>
            Points at a local weights file. Registration always triggers a golden-set
            evaluation (FR-12) — metrics are computed by the system itself, never entered by
            hand (RN-10).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid max-w-xl grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-version">Version</Label>
              <Input
                id="model-version"
                placeholder="v1.1.0"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="model-weights-path">Weights path</Label>
              <Input
                id="model-weights-path"
                className="font-mono text-xs"
                placeholder="/weights/v1.1.0.pt"
                value={weightsPath}
                onChange={(event) => setWeightsPath(event.target.value)}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              className="w-fit"
              disabled={registering || !version.trim() || !weightsPath.trim()}
              onClick={() => void handleRegister()}
            >
              Register version
            </Button>
            {registerError && <p className="text-sm text-destructive">{registerError}</p>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Versions</CardTitle>
          <CardDescription>
            Only one version is active at a time — activating a new one reloads the inference
            worker without dropping in-flight requests.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Version</TableHead>
                <TableHead>Evaluation</TableHead>
                <TableHead>Metrics</TableHead>
                <TableHead>Registered</TableHead>
                <TableHead>Activation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.map((modelVersion) => (
                <TableRow key={modelVersion.id}>
                  <TableCell className="font-medium">{modelVersion.version}</TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <Badge variant={STATUS_VARIANT[modelVersion.evaluation_status]}>
                        {STATUS_LABEL[modelVersion.evaluation_status]}
                      </Badge>
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
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(modelVersion.created_at).toLocaleString()}
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
                    No model versions registered yet.
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

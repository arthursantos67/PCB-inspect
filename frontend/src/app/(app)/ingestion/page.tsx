"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PathField } from "@/components/ingestion/PathField";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  getIngestionStatus,
  importFiles,
  scanDirectory,
  updateConfig,
  type FileResult,
  type ImportSummary,
  type IngestionStatus,
  type ScanSummary,
} from "@/lib/api-client";

const STATUS_LABEL: Record<IngestionStatus["status"], string> = {
  watching: "Watching",
  paused: "Paused",
  not_configured: "Not configured",
  error: "Error",
};

const STATUS_VARIANT: Record<
  IngestionStatus["status"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  watching: "default",
  paused: "secondary",
  not_configured: "outline",
  error: "destructive",
};

function FileResultList({ files }: { files: FileResult[] }) {
  const notable = files.filter((file) => file.outcome !== "ingested");
  if (notable.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
      {notable.map((file) => (
        <li key={file.path}>
          <span className="font-mono">{file.path}</span> — {file.outcome}
          {file.reason ? `: ${file.reason}` : ""}
        </li>
      ))}
    </ul>
  );
}

export default function IngestionPage() {
  const [status, setStatus] = useState<IngestionStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [watchRootPath, setWatchRootPath] = useState("");
  const [scanPath, setScanPath] = useState("");
  const [scanResult, setScanResult] = useState<ScanSummary | null>(null);

  const [importResult, setImportResult] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await getIngestionStatus();
      setStatus(next);
      setStatusError(null);
      // Only seed the field from the server once — don't clobber an in-progress edit.
      setWatchRootPath((current) => current || (next.watch_root_path ?? ""));
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : "Failed to load ingestion status.");
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const interval = setInterval(() => void refreshStatus(), 5000);
    return () => clearInterval(interval);
  }, [refreshStatus]);

  async function handleSaveWatchRoot(path: string) {
    await updateConfig({ watch_root_path: path });
    await refreshStatus();
  }

  async function handleToggleWatchMode() {
    if (!status) return;
    await updateConfig({ watch_mode_enabled: !status.watch_mode_enabled });
    await refreshStatus();
  }

  async function handleScan(path: string) {
    setScanResult(null);
    const summary = await scanDirectory(path);
    setScanResult(summary);
    await refreshStatus();
  }

  async function handleImportFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (list.length === 0) return;
    setImportError(null);
    setImportResult(null);
    try {
      const summary = await importFiles(list);
      setImportResult(summary);
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : "Import failed. Please try again.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Ingestion</h1>
        <p className="text-sm text-muted-foreground">
          Configure directory watching and run one-off scans or ad hoc imports.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Watch-mode status</CardTitle>
          <CardDescription>
            Continuous ingestion of the configured watch root (FR-03).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {statusError && <p className="text-sm text-destructive">{statusError}</p>}
          {status && (
            <>
              <div className="flex items-center gap-3">
                <Badge variant={STATUS_VARIANT[status.status]}>{STATUS_LABEL[status.status]}</Badge>
                {status.watch_root_path && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {status.watch_root_path}
                  </span>
                )}
                {status.detail && <span className="text-xs text-destructive">{status.detail}</span>}
              </div>
              <div className="flex gap-6 text-sm text-muted-foreground">
                <span>Discovered: {status.files_discovered}</span>
                <span>Ingested: {status.files_ingested}</span>
                <span>Failed: {status.files_failed}</span>
              </div>
              {status.watch_root_path && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-fit"
                  onClick={() => void handleToggleWatchMode()}
                >
                  {status.watch_mode_enabled ? "Pause watching" : "Resume watching"}
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Watch root</CardTitle>
          <CardDescription>
            Absolute path to the directory the camera writes into. Each subdirectory is a batch;
            each image inside it is a board.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PathField
            id="watch-root-path"
            label="Watch root path"
            value={watchRootPath}
            onChange={setWatchRootPath}
            onSubmit={handleSaveWatchRoot}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scan a directory now</CardTitle>
          <CardDescription>
            One-off scan of an arbitrary local path, without enabling continuous watching.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <PathField
            id="scan-path"
            label="Directory to scan"
            value={scanPath}
            onChange={setScanPath}
            onSubmit={handleScan}
            submitLabel="Scan directory now"
          />
          {scanResult && (
            <div className="rounded-lg border p-3 text-sm">
              <p>
                Discovered {scanResult.discovered} · Ingested {scanResult.ingested} · Duplicate{" "}
                {scanResult.duplicate} · Failed {scanResult.failed} · Skipped {scanResult.skipped}
              </p>
              <FileResultList files={scanResult.files} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ad hoc import</CardTitle>
          <CardDescription>
            Drag in a handful of stray files that aren&apos;t already under the watch root.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div
            role="button"
            tabIndex={0}
            aria-label="Drop image files here, or activate to choose files"
            className={`flex h-32 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed text-sm text-muted-foreground transition-colors focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 ${
              dragActive ? "border-primary bg-muted/50" : "border-border"
            }`}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              void handleImportFiles(event.dataTransfer.files);
            }}
          >
            Drop image files here, or click to choose
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/tiff,image/bmp"
            className="hidden"
            onChange={(event) => {
              if (event.target.files) void handleImportFiles(event.target.files);
              event.target.value = "";
            }}
          />
          {importError && <p className="text-sm text-destructive">{importError}</p>}
          {importResult && (
            <div className="rounded-lg border p-3 text-sm">
              <p>
                Ingested {importResult.ingested} · Duplicate {importResult.duplicate} · Failed{" "}
                {importResult.failed}
              </p>
              <FileResultList files={importResult.files} />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

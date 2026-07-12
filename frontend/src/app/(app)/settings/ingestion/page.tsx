"use client";

import { useEffect, useState } from "react";

import { PathField } from "@/components/ingestion/PathField";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ApiError,
  getConfig,
  scanDirectory,
  updateConfig,
  type FileResult,
  type ScanSummary,
} from "@/lib/api-client";

const NAMING_CONVENTION_LABEL: Record<string, string> = {
  subdirectory_batch_filename_board:
    "Immediate subdirectory = batch, filename = board (default)",
};

function ScanFileResultList({ files }: { files: FileResult[] }) {
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

export default function SettingsIngestionPage() {
  const [watchRootPath, setWatchRootPath] = useState("");
  const [namingConvention, setNamingConvention] = useState("subdirectory_batch_filename_board");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [scanPath, setScanPath] = useState("");
  const [scanResult, setScanResult] = useState<ScanSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { config } = await getConfig();
        if (cancelled) return;
        if (typeof config.watch_root_path === "string") setWatchRootPath(config.watch_root_path);
        if (typeof config.watch_naming_convention === "string") {
          setNamingConvention(config.watch_naming_convention);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof ApiError ? err.message : "Failed to load configuration.");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSaveWatchRoot(path: string) {
    await updateConfig({ watch_root_path: path });
  }

  async function handleNamingConventionChange(value: string) {
    setNamingConvention(value);
    await updateConfig({ watch_naming_convention: value });
  }

  async function handleScan(path: string) {
    setScanResult(null);
    const summary = await scanDirectory(path);
    setScanResult(summary);
  }

  return (
    <div className="flex flex-col gap-6">
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Watch root</CardTitle>
          <CardDescription>
            Absolute path to the directory the camera writes into (FR-03). Takes effect on the
            next scan or watch-mode poll — no restart required.
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
          <CardTitle>Batch/board naming convention</CardTitle>
          <CardDescription>
            How batch and board numbers are derived from the directory layout.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Label htmlFor="naming-convention">Naming convention</Label>
          <Select
            value={namingConvention}
            onValueChange={(value) => value && void handleNamingConventionChange(value)}
          >
            <SelectTrigger id="naming-convention" className="w-full max-w-md">
              <SelectValue>{(value: string) => NAMING_CONVENTION_LABEL[value] ?? value}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {Object.entries(NAMING_CONVENTION_LABEL).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
              <ScanFileResultList files={scanResult.files} />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

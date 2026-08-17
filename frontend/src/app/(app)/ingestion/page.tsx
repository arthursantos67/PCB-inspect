"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FolderPicker } from "@/components/ingestion/FolderPicker";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LampChip, type LampTone } from "@/components/ui/lamp-chip";
import { useI18n } from "@/contexts/I18nContext";
import {
  ApiError,
  getIngestionStatus,
  scanDirectory,
  updateConfig,
  type FileResult,
  type IngestionStatus,
  type ScanSummary,
} from "@/lib/api-client";

/** Watching is the only state that is doing something, so it is the only one that pulses.
 * Paused is a deliberate stop rather than a fault, so it stays graphite instead of amber.
 */
const STATUS_LAMP: Record<
  IngestionStatus["status"],
  { tone: LampTone; pulse?: boolean; hollow?: boolean }
> = {
  watching: { tone: "good", pulse: true },
  paused: { tone: "neutral" },
  not_configured: { tone: "neutral", hollow: true },
  error: { tone: "critical" },
};

function FileResultList({ files }: { files: FileResult[] }) {
  const { t } = useI18n();
  const notable = files.filter((file) => file.outcome !== "ingested");
  if (notable.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
      {notable.map((file) => (
        <li key={file.path}>
          <span className="font-mono">{file.path}</span>: {t(`ingestion.outcome.${file.outcome}`)}
          {file.reason ? ` (${file.reason})` : ""}
        </li>
      ))}
    </ul>
  );
}

export default function IngestionPage() {
  const { t } = useI18n();
  const [status, setStatus] = useState<IngestionStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [browsing, setBrowsing] = useState(false);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [savingFolder, setSavingFolder] = useState(false);

  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanSummary | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await getIngestionStatus();
      setStatus(next);
      setStatusError(null);
    } catch (err) {
      // The empty string stands for "failed, with nothing specific to say" — the generic
      // wording is picked at render time so a language switch doesn't restart the poller.
      setStatusError(err instanceof ApiError ? err.message : "");
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const interval = setInterval(() => void refreshStatus(), 5000);
    return () => clearInterval(interval);
  }, [refreshStatus]);

  async function handleToggleWatchMode() {
    if (!status) return;
    await updateConfig({ watch_mode_enabled: !status.watch_mode_enabled });
    await refreshStatus();
  }

  /** Pointing watch mode at a folder is the only way boards enter the system (FR-03): the
   * backend reads the images in place from that folder, so nothing is uploaded or copied.
   */
  async function handleSelectWatchRoot(path: string) {
    setBrowsing(false);
    setFolderError(null);
    setScanResult(null);
    setSavingFolder(true);
    try {
      await updateConfig({ watch_root_path: path });
      await refreshStatus();
    } catch (err) {
      setFolderError(err instanceof ApiError ? err.message : t("ingestion.folderFailed"));
    } finally {
      setSavingFolder(false);
    }
  }

  /** Watch mode already polls every few seconds; this runs the same scan immediately so the
   * operator sees what a folder they just picked contains without waiting for the next poll.
   */
  async function handleScanNow() {
    if (!status?.watch_root_path) return;
    setScanError(null);
    setScanResult(null);
    setScanning(true);
    try {
      setScanResult(await scanDirectory(status.watch_root_path));
      await refreshStatus();
    } catch (err) {
      setScanError(err instanceof ApiError ? err.message : t("ingestion.scanFailed"));
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t("ingestion.eyebrow")}
        title={t("ingestion.title")}
        description={
          <>
            {t("ingestion.descriptionStart")}
            <Link href="/settings/ingestion" className="text-brand-ink underline-offset-2 hover:underline">
              {t("ingestion.descriptionLink")}
            </Link>
            {t("ingestion.descriptionEnd")}
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>{t("ingestion.card.title")}</CardTitle>
          <CardDescription>{t("ingestion.card.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {statusError !== null && (
            <p className="text-sm text-destructive">{statusError || t("ingestion.statusFailed")}</p>
          )}
          {status && (
            <>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <LampChip {...STATUS_LAMP[status.status]}>
                  {t(`ingestion.status.${status.status}`)}
                </LampChip>
                {status.watch_root_path ? (
                  <span className="ident truncate text-muted-foreground">
                    {status.watch_root_path}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">{t("ingestion.noFolder")}</span>
                )}
                {status.detail && <span className="text-xs text-destructive">{status.detail}</span>}
              </div>
              {/* The three counters are the operator's only live feedback that the folder is
                  being read, so they are set as readings rather than a sentence. */}
              <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-border bg-border shadow-panel">
                {(
                  [
                    { key: "discovered", value: status.files_discovered },
                    { key: "ingested", value: status.files_ingested },
                    { key: "failed", value: status.files_failed },
                  ] as const
                ).map((counter) => (
                  <div key={counter.key} className="bg-card px-3 py-2.5">
                    <dt className="label-channel">{t(`ingestion.counter.${counter.key}`)}</dt>
                    <dd
                      className={`readout mt-1.5 text-lg leading-none font-semibold ${
                        counter.key === "failed" && counter.value > 0 ? "text-status-critical" : ""
                      }`}
                    >
                      {counter.value}
                    </dd>
                  </div>
                ))}
              </dl>
              {/* Whichever button moves the folder from idle to running carries the brand face:
                  with no folder chosen that is picking one, and once one is chosen and paused it
                  is resuming. Everything else on the card stays an outline control. */}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant={status.watch_root_path ? "outline" : "brand"}
                  size="sm"
                  disabled={savingFolder}
                  onClick={() => setBrowsing((open) => !open)}
                >
                  {savingFolder
                    ? t("ingestion.saving")
                    : status.watch_root_path
                      ? t("ingestion.changeFolder")
                      : t("ingestion.chooseFolder")}
                </Button>
                {status.watch_root_path && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={scanning}
                      onClick={() => void handleScanNow()}
                    >
                      {scanning ? t("ingestion.scanning") : t("ingestion.scanNow")}
                    </Button>
                    <Button
                      variant={status.watch_mode_enabled ? "outline" : "brand"}
                      size="sm"
                      onClick={() => void handleToggleWatchMode()}
                    >
                      {status.watch_mode_enabled
                        ? t("ingestion.pauseWatching")
                        : t("ingestion.resumeWatching")}
                    </Button>
                  </>
                )}
              </div>
            </>
          )}

          {browsing && (
            <FolderPicker
              startPath={status?.watch_root_path ?? undefined}
              onSelect={(path) => void handleSelectWatchRoot(path)}
              onCancel={() => setBrowsing(false)}
            />
          )}
          {folderError && <p className="text-sm text-destructive">{folderError}</p>}
          {scanError && <p className="text-sm text-destructive">{scanError}</p>}
          {scanResult && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
              <p className="ident truncate text-muted-foreground">{scanResult.path}</p>
              <p className="mt-1">
                {t("ingestion.scanSummary", {
                  discovered: scanResult.discovered,
                  ingested: scanResult.ingested,
                  duplicate: scanResult.duplicate,
                  failed: scanResult.failed,
                  skipped: scanResult.skipped,
                })}
              </p>
              <FileResultList files={scanResult.files} />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

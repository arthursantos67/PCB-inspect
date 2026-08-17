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
import { useI18n } from "@/contexts/I18nContext";
import {
  ApiError,
  getConfig,
  scanDirectory,
  updateConfig,
  type FileResult,
  type ScanSummary,
} from "@/lib/api-client";

// The conventions the backend understands; the words come from the dictionaries, keyed by the
// same value the API stores.
const NAMING_CONVENTIONS = ["subdirectory_batch_filename_board"] as const;
type NamingConvention = (typeof NAMING_CONVENTIONS)[number];

function ScanFileResultList({ files }: { files: FileResult[] }) {
  const { t } = useI18n();
  const notable = files.filter((file) => file.outcome !== "ingested");
  if (notable.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
      {notable.map((file) => (
        <li key={file.path}>
          <span className="font-mono">{file.path}</span>: {t(`ingestion.outcome.${file.outcome}`)}
          {file.reason ? `: ${file.reason}` : ""}
        </li>
      ))}
    </ul>
  );
}

export default function SettingsIngestionPage() {
  const { t } = useI18n();
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
        // The empty string stands for "failed, with nothing specific to say" — the generic
        // wording is picked at render time, keeping this one-shot effect language-independent.
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "");
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
      {loadError !== null && (
        <p className="text-sm text-destructive">
          {loadError || t("settings.ingestion.loadFailed")}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.ingestion.watchRoot.title")}</CardTitle>
          <CardDescription>{t("settings.ingestion.watchRoot.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <PathField
            id="watch-root-path"
            label={t("settings.ingestion.watchRoot.label")}
            value={watchRootPath}
            onChange={setWatchRootPath}
            onSubmit={handleSaveWatchRoot}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.ingestion.naming.title")}</CardTitle>
          <CardDescription>{t("settings.ingestion.naming.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Label htmlFor="naming-convention">{t("settings.ingestion.naming.label")}</Label>
          <Select
            value={namingConvention}
            onValueChange={(value) => value && void handleNamingConventionChange(value)}
          >
            <SelectTrigger id="naming-convention" className="w-full max-w-md">
              <SelectValue>
                {(value: string) =>
                  NAMING_CONVENTIONS.includes(value as NamingConvention)
                    ? t(`settings.ingestion.naming.option.${value as NamingConvention}`)
                    : value
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {NAMING_CONVENTIONS.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`settings.ingestion.naming.option.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.ingestion.scan.title")}</CardTitle>
          <CardDescription>{t("settings.ingestion.scan.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <PathField
            id="scan-path"
            label={t("settings.ingestion.scan.label")}
            value={scanPath}
            onChange={setScanPath}
            onSubmit={handleScan}
            submitLabel={t("settings.ingestion.scan.submit")}
          />
          {scanResult && (
            <div className="rounded-lg border p-3 text-sm">
              <p>
                {t("ingestion.scanSummary", {
                  discovered: scanResult.discovered,
                  ingested: scanResult.ingested,
                  duplicate: scanResult.duplicate,
                  failed: scanResult.failed,
                  skipped: scanResult.skipped,
                })}
              </p>
              <ScanFileResultList files={scanResult.files} />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

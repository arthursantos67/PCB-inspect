"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";
import { ApiError, browseDirectories, type DirectoryListing } from "@/lib/api-client";

/** Browses the host filesystem one level at a time so the operator can pick a watch root by
 * clicking through their own folders. A browser page can't open a native OS folder picker, and
 * the backend is the only side with filesystem access, so the listing comes from the API.
 */
export function FolderPicker({
  startPath,
  onSelect,
  onCancel,
}: {
  startPath?: string;
  onSelect: (path: string) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const browse = useCallback(async (path?: string) => {
    setLoading(true);
    setError(null);
    try {
      setListing(await browseDirectories(path));
    } catch (err) {
      // The empty string stands for "failed, with nothing specific to say"; the wording is
      // chosen at render time so this callback stays independent of the current language.
      setError(err instanceof ApiError ? err.message : "");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    async function open() {
      if (!startPath) {
        await browse();
        return;
      }
      try {
        setListing(await browseDirectories(startPath));
      } catch {
        // The saved path may not be browsable (a stale entry, or a container-internal path from
        // before the host mount existed) — fall back to the root rather than a dead end.
        await browse();
      }
    }
    void open();
  }, [browse, startPath]);

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs text-muted-foreground">
          {listing?.path ?? t("ingestion.picker.loading")}
        </span>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!listing?.parent || loading}
            onClick={() => void browse(listing?.parent ?? undefined)}
          >
            {t("ingestion.picker.up")}
          </Button>
          <Button size="sm" disabled={!listing} onClick={() => listing && onSelect(listing.path)}>
            {t("ingestion.picker.use")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t("ingestion.picker.cancel")}
          </Button>
        </div>
      </div>

      {error !== null && (
        <p className="text-sm text-destructive">{error || t("ingestion.picker.failed")}</p>
      )}

      <ul className="max-h-64 overflow-y-auto">
        {listing?.directories.length === 0 && !loading && (
          <li className="px-2 py-1.5 text-sm text-muted-foreground">
            {t("ingestion.picker.empty")}
          </li>
        )}
        {listing?.directories.map((entry) => (
          <li key={entry.path}>
            <button
              type="button"
              className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
              onClick={() => void browse(entry.path)}
            >
              {entry.name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

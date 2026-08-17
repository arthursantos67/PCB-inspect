"use client";

import { useState, type FormEvent } from "react";

import { FolderPicker } from "@/components/ingestion/FolderPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/contexts/I18nContext";
import { ApiError } from "@/lib/api-client";

// FE-05: a plain browser page can't open a native OS folder picker, so the path is either typed
// or picked by browsing the host filesystem through the API (`FolderPicker`), and the backend —
// which does have filesystem access — validates it either way.
type PathFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (path: string) => Promise<void>;
  /** Already translated by the caller, which is the side that knows what is being saved.
   * Left out, the button reads as a plain "Save" in the station language.
   */
  submitLabel?: string;
};

export function PathField({ id, label, value, onChange, onSubmit, submitLabel }: PathFieldProps) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [browsing, setBrowsing] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    setSubmitting(true);
    try {
      await onSubmit(value);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("ingestion.path.failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="flex flex-col gap-2" onSubmit={handleSubmit}>
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setSuccess(false);
            setError(null);
          }}
          placeholder={t("ingestion.path.placeholder")}
          className="font-mono text-xs"
          aria-invalid={error ? true : undefined}
        />
        <Button type="button" variant="outline" onClick={() => setBrowsing((open) => !open)}>
          {t("ingestion.path.browse")}
        </Button>
        <Button type="submit" disabled={submitting || !value.trim()}>
          {submitLabel ?? t("ingestion.path.save")}
        </Button>
      </div>
      {browsing && (
        <FolderPicker
          startPath={value.trim() || undefined}
          onSelect={(path) => {
            onChange(path);
            setBrowsing(false);
            setSuccess(false);
            setError(null);
          }}
          onCancel={() => setBrowsing(false)}
        />
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {success && !error && (
        <p className="text-sm text-muted-foreground">{t("ingestion.path.validated")}</p>
      )}
    </form>
  );
}

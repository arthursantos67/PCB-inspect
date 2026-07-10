"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";

// FE-05: a plain browser page can't open a native OS folder picker, so the operator types or
// pastes an absolute path and the backend — which does have filesystem access — validates it.
type PathFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (path: string) => Promise<void>;
  submitLabel?: string;
};

export function PathField({ id, label, value, onChange, onSubmit, submitLabel = "Save" }: PathFieldProps) {
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    setSubmitting(true);
    try {
      await onSubmit(value);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
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
          placeholder="/absolute/path/to/directory"
          className="font-mono text-xs"
          aria-invalid={error ? true : undefined}
        />
        <Button type="submit" disabled={submitting || !value.trim()}>
          {submitLabel}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {success && !error && <p className="text-sm text-muted-foreground">Path validated.</p>}
    </form>
  );
}

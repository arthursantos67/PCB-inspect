"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DefectBadge } from "@/components/dashboard/DefectBadge";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LampChip } from "@/components/ui/lamp-chip";
import { useI18n } from "@/contexts/I18nContext";
import { ApiError, listModelVersions, type ModelVersion } from "@/lib/api-client";
import { DEFECT_TYPES } from "@/lib/chart-colors";
import { formatTimestamp } from "@/lib/format";

// PRD section 4.1 — the artifact the product ships with. Stated here so the operator can read
// what the model is without opening the notebook; the notebook is the full method.
const TRAINING_NOTEBOOK_URL =
  "https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing";

// Only the row order lives here; both halves of each row come from the dictionaries, so the
// spec plate reads in the station language.
const TRAINING_FACTS = [
  "architecture",
  "resolution",
  "data",
  "run",
  "map50",
  "map5095",
] as const;

function ActiveModelCard() {
  const { t } = useI18n();
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setVersions(await listModelVersions());
      } catch (err) {
        // The empty string stands for "failed, with nothing specific to say"; the wording is
        // picked at render time so this one-shot effect stays language-independent.
        setError(err instanceof ApiError ? err.message : "");
      }
    }
    void load();
  }, []);

  const active = versions?.find((version) => version.is_active) ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("model.active.title")}</CardTitle>
        <CardDescription>{t("model.active.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {error !== null && (
          <p className="text-destructive">{error || t("model.active.loadFailed")}</p>
        )}
        {error === null && versions === null && (
          <p className="text-muted-foreground">{t("common.loading")}</p>
        )}
        {versions !== null && active === null && (
          <p className="text-muted-foreground">
            {t("model.active.noneStart")}
            <Link className="underline" href="/settings/models">
              {t("model.link.settingsModels")}
            </Link>
            {t("model.active.noneEnd")}
          </p>
        )}
        {active && (
          <>
            {/* The version string is an identifier an operator quotes back, so it is set in the
                identifier face on a plate rather than in a filled pill. The lamp beside it says
                the state, matching the same chip in Settings > Models. */}
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="ident rounded-[5px] border border-border-strong bg-card px-2 py-1 text-[0.8125rem] font-semibold">
                {active.version}
              </span>
              <LampChip tone="good">{t("model.active.inProduction")}</LampChip>
              {active.activated_at && (
                <span className="text-[0.8125rem] text-muted-foreground">
                  {t("model.active.since", { timestamp: formatTimestamp(active.activated_at) })}
                </span>
              )}
            </div>
            {active.metrics && (
              <p className="text-muted-foreground">
                {t("model.active.metrics", {
                  map50: (active.metrics.map50 * 100).toFixed(2),
                  map5095: (active.metrics.map50_95 * 100).toFixed(2),
                })}
              </p>
            )}
            <p className="ident break-all text-muted-foreground">{active.weights_path}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function ModelPage() {
  const { t } = useI18n();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t("model.eyebrow")}
        title={t("model.title")}
        description={t("model.description")}
      />

      <ActiveModelCard />

      <Card>
        <CardHeader>
          <CardTitle>{t("model.detects.title")}</CardTitle>
          <CardDescription>{t("model.detects.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          {/* Same six hues as every chart in the app: the class list is where an operator
              learns the color code, so it is taught here rather than in a legend. */}
          <ul className="flex flex-wrap gap-2">
            {DEFECT_TYPES.map((defectType) => (
              <li key={defectType}>
                <DefectBadge defectType={defectType} />
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            {t("model.detects.thresholdsStart")}
            <Link className="underline" href="/settings/detection">
              {t("model.link.settingsDetection")}
            </Link>
            {t("model.detects.thresholdsEnd")}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("model.training.title")}</CardTitle>
          <CardDescription>{t("model.training.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          {/* A spec plate: the label engraved on the left, the measured value on the right,
              read down the column the way a datasheet is read. */}
          <dl className="overflow-hidden rounded-md border border-border">
            {TRAINING_FACTS.map((fact) => (
              <div
                key={fact}
                className="flex flex-col gap-1 border-b border-border px-3 py-2.5 last:border-0 sm:flex-row sm:items-baseline sm:gap-6"
              >
                {/* "mAP" is a term of art, so the channel label's uppercasing is turned off
                    for rows whose label carries one rather than mangling it to "MAP". */}
                <dt
                  className={`label-channel sm:w-56 sm:shrink-0 ${
                    fact.startsWith("map") ? "normal-case" : ""
                  }`}
                >
                  {t(`model.training.fact.${fact}.label`)}
                </dt>
                <dd className="text-[0.8125rem]">{t(`model.training.fact.${fact}.value`)}</dd>
              </div>
            ))}
          </dl>
          <p>
            <a
              className="underline"
              href={TRAINING_NOTEBOOK_URL}
              target="_blank"
              rel="noreferrer noopener"
            >
              {t("model.training.notebookLink")}
            </a>
          </p>
          <p className="text-muted-foreground">
            {t("model.training.noteStart")}
            <code>best.pt</code>
            {t("model.training.noteMiddle")}
            <Link className="underline" href="/settings/models">
              {t("model.link.settingsModels")}
            </Link>
            {t("model.training.noteEnd")}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("model.limits.title")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>{t("model.limits.dataset")}</p>
          <p>{t("model.limits.line")}</p>
        </CardContent>
      </Card>
    </div>
  );
}

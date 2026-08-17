"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LampChip, type LampTone } from "@/components/ui/lamp-chip";
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
  getHealth,
  updateConfig,
  type AgentAnalysisMode,
  type HealthCheckResult,
  type LlmProvider,
  type SecretConfigValue,
} from "@/lib/api-client";
import { DEFECT_TYPES, SEVERITIES, type Severity } from "@/lib/chart-colors";

const DEFAULTS = {
  minConfidenceStore: 0.25,
  minConfidenceReport: 0.5,
  agentAnalysisMode: "conditional" as AgentAnalysisMode,
  agentAnalysisMinDefectCount: 3,
  agentAnalysisCriticalClasses: [] as string[],
  agentAnalysisMinSeverity: "high",
  llmProvider: "openai_compatible" as LlmProvider,
  llmBaseUrl: "http://host.docker.internal:1234/v1",
  llmModel: "local-model",
  llmTimeoutS: 60,
  alertDefectRateThreshold: 0.15,
  alertWindowMinutes: 60,
};

// Only the option order lives here now; the words come from the dictionaries, keyed by the
// same value the API stores, so both languages stay in step with the enum.
const AGENT_MODES: readonly AgentAnalysisMode[] = ["conditional", "always", "on_demand"];

const PROVIDERS: readonly LlmProvider[] = ["openai_compatible", "anthropic", "google"];

// Mirrors `app.agents.llm_client.LLM_ROLES`. Order is the order the blocks render in, chosen
// to match how often an operator touches them rather than the backend's tuple order.
const LLM_ROLES = ["chat", "analysis", "report"] as const;
type LlmRole = (typeof LLM_ROLES)[number];

type RoleConnection = {
  baseUrl: string;
  model: string;
  apiKeyInput: string;
  reasoningEffort: string;
};

const EMPTY_ROLE_CONNECTION: RoleConnection = {
  baseUrl: "",
  model: "",
  apiKeyInput: "",
  reasoningEffort: "",
};
const EMPTY_SECRET: SecretConfigValue = { configured: false, last4: null };

const EMPTY_ROLE_CONNECTIONS = Object.fromEntries(
  LLM_ROLES.map((role) => [role, EMPTY_ROLE_CONNECTION])
) as Record<LlmRole, RoleConnection>;

const EMPTY_ROLE_KEY_STATUS = Object.fromEntries(
  LLM_ROLES.map((role) => [role, EMPTY_SECRET])
) as Record<LlmRole, SecretConfigValue>;

const HEALTH_LAMP: Record<HealthCheckResult["status"], { tone: LampTone; hollow?: boolean }> = {
  ok: { tone: "good" },
  error: { tone: "critical" },
  not_configured: { tone: "neutral", hollow: true },
};

function isSecretConfigValue(value: unknown): value is SecretConfigValue {
  return typeof value === "object" && value !== null && "configured" in value;
}

function SaveFeedback({ error, saved }: { error: string | null; saved: boolean }) {
  const { t } = useI18n();
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (saved) return <p className="text-sm text-muted-foreground">{t("common.saved")}</p>;
  return null;
}

export default function SettingsDetectionPage() {
  const { t } = useI18n();
  const [loadError, setLoadError] = useState<string | null>(null);

  // Confidence thresholds (RV-03)
  const [minConfidenceStore, setMinConfidenceStore] = useState(DEFAULTS.minConfidenceStore);
  const [minConfidenceReport, setMinConfidenceReport] = useState(DEFAULTS.minConfidenceReport);
  const [thresholdsError, setThresholdsError] = useState<string | null>(null);
  const [thresholdsSaved, setThresholdsSaved] = useState(false);

  // Agent analysis policy (FR-06)
  const [agentMode, setAgentMode] = useState<AgentAnalysisMode>(DEFAULTS.agentAnalysisMode);
  const [minDefectCount, setMinDefectCount] = useState(DEFAULTS.agentAnalysisMinDefectCount);
  const [criticalClasses, setCriticalClasses] = useState<string[]>(
    DEFAULTS.agentAnalysisCriticalClasses
  );
  const [minSeverity, setMinSeverity] = useState(DEFAULTS.agentAnalysisMinSeverity);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [policySaved, setPolicySaved] = useState(false);

  // LLM connection (section 5.2)
  const [provider, setProvider] = useState<LlmProvider>(DEFAULTS.llmProvider);
  const [baseUrl, setBaseUrl] = useState(DEFAULTS.llmBaseUrl);
  const [model, setModel] = useState(DEFAULTS.llmModel);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiKeyStatus, setApiKeyStatus] = useState<SecretConfigValue>({
    configured: false,
    last4: null,
  });
  const [timeoutS, setTimeoutS] = useState(DEFAULTS.llmTimeoutS);
  // Per-role endpoint overrides. Held as one record keyed by role so the three blocks render
  // from a loop instead of nine near-identical useStates; an empty string means "inherit the
  // connection above", which is exactly what the backend does with an unset key.
  const [roleConnections, setRoleConnections] = useState<Record<LlmRole, RoleConnection>>(
    EMPTY_ROLE_CONNECTIONS
  );
  const [roleKeyStatus, setRoleKeyStatus] = useState<Record<LlmRole, SecretConfigValue>>(
    EMPTY_ROLE_KEY_STATUS
  );
  const [llmError, setLlmError] = useState<string | null>(null);
  const [llmSaved, setLlmSaved] = useState(false);
  const [llmHealth, setLlmHealth] = useState<HealthCheckResult | null>(null);
  const [checkingLlm, setCheckingLlm] = useState(false);

  // Quality alert thresholds (FR-19)
  const [alertRateThreshold, setAlertRateThreshold] = useState(
    DEFAULTS.alertDefectRateThreshold
  );
  const [alertWindowMinutes, setAlertWindowMinutes] = useState(DEFAULTS.alertWindowMinutes);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [alertsSaved, setAlertsSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { config } = await getConfig();
        if (cancelled) return;

        if (typeof config.min_confidence_store === "number") {
          setMinConfidenceStore(config.min_confidence_store);
        }
        if (typeof config.min_confidence_report === "number") {
          setMinConfidenceReport(config.min_confidence_report);
        }

        if (typeof config.agent_analysis_mode === "string") {
          setAgentMode(config.agent_analysis_mode as AgentAnalysisMode);
        }
        if (typeof config.agent_analysis_min_defect_count === "number") {
          setMinDefectCount(config.agent_analysis_min_defect_count);
        }
        if (Array.isArray(config.agent_analysis_critical_classes)) {
          setCriticalClasses(config.agent_analysis_critical_classes as string[]);
        }
        if (typeof config.agent_analysis_min_severity === "string") {
          setMinSeverity(config.agent_analysis_min_severity);
        }

        if (typeof config["llm.provider"] === "string") {
          setProvider(config["llm.provider"] as LlmProvider);
        }
        if (typeof config["llm.base_url"] === "string") setBaseUrl(config["llm.base_url"]);
        if (typeof config["llm.model"] === "string") setModel(config["llm.model"]);
        if (typeof config["llm.timeout_s"] === "number") setTimeoutS(config["llm.timeout_s"]);
        if (isSecretConfigValue(config["llm.api_key"])) setApiKeyStatus(config["llm.api_key"]);

        setRoleConnections((current) => {
          const next = { ...current };
          for (const role of LLM_ROLES) {
            const baseUrl = config[`llm.${role}.base_url`];
            const model = config[`llm.${role}.model`];
            const reasoningEffort = config[`llm.${role}.reasoning_effort`];
            next[role] = {
              baseUrl: typeof baseUrl === "string" ? baseUrl : "",
              model: typeof model === "string" ? model : "",
              apiKeyInput: "",
              reasoningEffort: typeof reasoningEffort === "string" ? reasoningEffort : "",
            };
          }
          return next;
        });
        setRoleKeyStatus((current) => {
          const next = { ...current };
          for (const role of LLM_ROLES) {
            const key = config[`llm.${role}.api_key`];
            if (isSecretConfigValue(key)) next[role] = key;
          }
          return next;
        });

        if (typeof config.alert_defect_rate_threshold === "number") {
          setAlertRateThreshold(config.alert_defect_rate_threshold);
        }
        if (typeof config.alert_window_minutes === "number") {
          setAlertWindowMinutes(config.alert_window_minutes);
        }
      } catch (err) {
        // The empty string stands for "failed, with nothing specific to say" — it keeps the
        // generic wording out of this effect, which runs once and must not depend on the
        // current language.
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function refreshLlmHealth() {
    setCheckingLlm(true);
    try {
      const health = await getHealth();
      setLlmHealth(health.llm);
    } catch {
      setLlmHealth({ status: "error", detail: t("detection.llm.healthFailed") });
    } finally {
      setCheckingLlm(false);
    }
  }

  useEffect(() => {
    void refreshLlmHealth();
  }, []);

  async function handleSaveThresholds() {
    setThresholdsError(null);
    setThresholdsSaved(false);
    try {
      await updateConfig({
        min_confidence_store: minConfidenceStore,
        min_confidence_report: minConfidenceReport,
      });
      setThresholdsSaved(true);
    } catch (err) {
      setThresholdsError(
        err instanceof ApiError ? err.message : t("detection.thresholds.saveFailed")
      );
    }
  }

  function toggleCriticalClass(defectType: string, checked: boolean) {
    setCriticalClasses((current) =>
      checked ? [...current, defectType] : current.filter((value) => value !== defectType)
    );
  }

  async function handleSavePolicy() {
    setPolicyError(null);
    setPolicySaved(false);
    try {
      await updateConfig({
        agent_analysis_mode: agentMode,
        agent_analysis_min_defect_count: minDefectCount,
        agent_analysis_critical_classes: criticalClasses,
        agent_analysis_min_severity: minSeverity,
      });
      setPolicySaved(true);
    } catch (err) {
      setPolicyError(err instanceof ApiError ? err.message : t("detection.policy.saveFailed"));
    }
  }

  async function handleSaveLlm() {
    setLlmError(null);
    setLlmSaved(false);
    try {
      const update: Record<string, unknown> = {
        "llm.provider": provider,
        "llm.model": model,
        "llm.timeout_s": timeoutS,
      };
      if (provider === "openai_compatible") update["llm.base_url"] = baseUrl;
      if (apiKeyInput.trim()) update["llm.api_key"] = apiKeyInput.trim();

      for (const role of LLM_ROLES) {
        const connection = roleConnections[role];
        // Sent even when empty: "" is the backend's documented "clear this key" signal, so
        // blanking a field in the form is what puts the role back on the shared connection.
        update[`llm.${role}.base_url`] = connection.baseUrl.trim();
        update[`llm.${role}.model`] = connection.model.trim();
        update[`llm.${role}.reasoning_effort`] = connection.reasoningEffort.trim();
        // The key is the exception — an untouched password field means "leave it alone",
        // not "erase it", since the stored value is never rendered back for comparison.
        if (connection.apiKeyInput.trim()) {
          update[`llm.${role}.api_key`] = connection.apiKeyInput.trim();
        }
      }

      const { config } = await updateConfig(update);
      if (isSecretConfigValue(config["llm.api_key"])) setApiKeyStatus(config["llm.api_key"]);
      setApiKeyInput("");
      setRoleKeyStatus((current) => {
        const next = { ...current };
        for (const role of LLM_ROLES) {
          const key = config[`llm.${role}.api_key`];
          if (isSecretConfigValue(key)) next[role] = key;
        }
        return next;
      });
      setRoleConnections((current) => {
        const next = { ...current };
        for (const role of LLM_ROLES) next[role] = { ...current[role], apiKeyInput: "" };
        return next;
      });
      setLlmSaved(true);
      await refreshLlmHealth();
    } catch (err) {
      setLlmError(err instanceof ApiError ? err.message : t("detection.llm.saveFailed"));
    }
  }

  async function handleSaveAlerts() {
    setAlertsError(null);
    setAlertsSaved(false);
    try {
      await updateConfig({
        alert_defect_rate_threshold: alertRateThreshold,
        alert_window_minutes: alertWindowMinutes,
      });
      setAlertsSaved(true);
    } catch (err) {
      setAlertsError(err instanceof ApiError ? err.message : t("detection.alerts.saveFailed"));
    }
  }

  const isCloudProvider = provider !== "openai_compatible";

  return (
    <div className="flex flex-col gap-6">
      {loadError !== null && (
        <p className="text-sm text-destructive">{loadError || t("detection.loadFailed")}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("detection.thresholds.title")}</CardTitle>
          <CardDescription>{t("detection.thresholds.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="min-confidence-store">{t("detection.thresholds.store")}</Label>
              <Input
                id="min-confidence-store"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={minConfidenceStore}
                onChange={(event) => setMinConfidenceStore(Number(event.target.value))}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="min-confidence-report">{t("detection.thresholds.report")}</Label>
              <Input
                id="min-confidence-report"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={minConfidenceReport}
                onChange={(event) => setMinConfidenceReport(Number(event.target.value))}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="brand" size="sm" className="w-fit" onClick={() => void handleSaveThresholds()}>
              {t("detection.thresholds.save")}
            </Button>
            <SaveFeedback error={thresholdsError} saved={thresholdsSaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("detection.policy.title")}</CardTitle>
          <CardDescription>{t("detection.policy.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="agent-analysis-mode">{t("detection.policy.mode")}</Label>
            <Select
              value={agentMode}
              onValueChange={(value) => setAgentMode(value as AgentAnalysisMode)}
            >
              <SelectTrigger id="agent-analysis-mode" className="w-full max-w-md">
                <SelectValue>
                  {(value: AgentAnalysisMode) => t(`detection.policy.mode.${value}`)}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {AGENT_MODES.map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {t(`detection.policy.mode.${mode}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {agentMode === "conditional" && (
            <div className="flex flex-col gap-4 rounded-lg border p-4">
              <p className="text-sm text-muted-foreground">
                {t("detection.policy.conditionalHint")}
              </p>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="min-defect-count">{t("detection.policy.minDefectCount")}</Label>
                <Input
                  id="min-defect-count"
                  type="number"
                  min={1}
                  step={1}
                  className="max-w-32"
                  value={minDefectCount}
                  onChange={(event) => setMinDefectCount(Number(event.target.value))}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">
                  {t("detection.policy.criticalClasses")}
                </span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {DEFECT_TYPES.map((defectType) => (
                    <label
                      key={defectType}
                      className="flex items-center gap-2 text-sm font-normal"
                    >
                      <Checkbox
                        checked={criticalClasses.includes(defectType)}
                        onCheckedChange={(checked) =>
                          toggleCriticalClass(defectType, checked === true)
                        }
                      />
                      {t(`defect.${defectType}`)}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="min-severity">{t("detection.policy.minSeverity")}</Label>
                <Select
                  value={minSeverity}
                  onValueChange={(value) => value && setMinSeverity(value)}
                >
                  <SelectTrigger id="min-severity" className="w-full max-w-48">
                    <SelectValue>
                      {/* A value the API stored but this build doesn't know shows as-is,
                          rather than as a missing-translation key. */}
                      {(value: string) =>
                        SEVERITIES.includes(value as Severity)
                          ? t(`severity.${value as Severity}`)
                          : value
                      }
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITIES.map((severity) => (
                      <SelectItem key={severity} value={severity}>
                        {t(`severity.${severity}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button variant="brand" size="sm" className="w-fit" onClick={() => void handleSavePolicy()}>
              {t("detection.policy.save")}
            </Button>
            <SaveFeedback error={policyError} saved={policySaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("detection.llm.title")}</CardTitle>
          <CardDescription>{t("detection.llm.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-provider">{t("detection.llm.provider")}</Label>
            <Select value={provider} onValueChange={(value) => setProvider(value as LlmProvider)}>
              <SelectTrigger id="llm-provider" className="w-full max-w-md">
                <SelectValue>
                  {(value: LlmProvider) => t(`detection.llm.provider.${value}`)}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`detection.llm.provider.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isCloudProvider && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
            >
              {t("detection.llm.cloudWarning", {
                provider: t(`detection.llm.provider.${provider}`),
              })}
            </div>
          )}

          {!isCloudProvider && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="llm-base-url">{t("detection.llm.baseUrl")}</Label>
              <Input
                id="llm-base-url"
                className="max-w-md font-mono text-xs"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="http://host.docker.internal:1234/v1"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-model">{t("detection.llm.model")}</Label>
            <Input
              id="llm-model"
              className="max-w-md"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </div>

          {/* Shown for every provider, not just the cloud ones. "OpenAI-compatible" stopped
              meaning "local and unauthenticated" the moment a hosted endpoint could be put
              behind it — Groq and Google both speak this dialect and both require a key, and
              hiding the field here left no way to enter one. */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-api-key">{t("detection.llm.apiKey")}</Label>
            <div className="flex items-center gap-2">
              <LampChip
                tone={apiKeyStatus.configured ? "good" : "neutral"}
                hollow={!apiKeyStatus.configured}
              >
                {apiKeyStatus.configured
                  ? t("detection.llm.apiKeyConfigured", { last4: apiKeyStatus.last4 ?? "" })
                  : t("detection.llm.apiKeyMissing")}
              </LampChip>
            </div>
            <Input
              id="llm-api-key"
              type="password"
              className="max-w-md"
              value={apiKeyInput}
              onChange={(event) => setApiKeyInput(event.target.value)}
              placeholder={t("detection.llm.apiKeyPlaceholder")}
              autoComplete="off"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-timeout">{t("detection.llm.timeout")}</Label>
            <Input
              id="llm-timeout"
              type="number"
              min={1}
              step={1}
              className="max-w-32"
              value={timeoutS}
              onChange={(event) => setTimeoutS(Number(event.target.value))}
            />
          </div>

          {/* Per-role overrides live inside this same card, under the shared connection they
              fall back to, and are written by the one save button below — three roles that
              mostly inherit are one setting with exceptions, not four separate settings. */}
          {!isCloudProvider && (
            <div className="flex flex-col gap-4 border-t border-border pt-4">
              <div className="flex flex-col gap-1">
                <span className="label-channel">{t("detection.llm.roles.title")}</span>
                <p className="text-sm text-muted-foreground">
                  {t("detection.llm.roles.description")}
                </p>
              </div>

              {LLM_ROLES.map((role) => {
                const connection = roleConnections[role];
                const keyStatus = roleKeyStatus[role];
                const update = (patch: Partial<RoleConnection>) =>
                  setRoleConnections((current) => ({
                    ...current,
                    [role]: { ...current[role], ...patch },
                  }));
                return (
                  <div
                    key={role}
                    className="flex flex-col gap-3 rounded-md border border-border p-3"
                  >
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium">
                        {t(`detection.llm.roles.${role}`)}
                      </span>
                      <p className="text-xs text-muted-foreground">
                        {t(`detection.llm.roles.${role}Hint`)}
                      </p>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`llm-${role}-base-url`}>{t("detection.llm.baseUrl")}</Label>
                      <Input
                        id={`llm-${role}-base-url`}
                        className="max-w-md font-mono text-xs"
                        value={connection.baseUrl}
                        onChange={(event) => update({ baseUrl: event.target.value })}
                        placeholder={t("detection.llm.roles.inherit")}
                      />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`llm-${role}-model`}>{t("detection.llm.model")}</Label>
                      <Input
                        id={`llm-${role}-model`}
                        className="max-w-md"
                        value={connection.model}
                        onChange={(event) => update({ model: event.target.value })}
                        placeholder={t("detection.llm.roles.inherit")}
                      />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`llm-${role}-reasoning`}>
                        {t("detection.llm.roles.reasoningEffort")}
                      </Label>
                      <Input
                        id={`llm-${role}-reasoning`}
                        className="max-w-md font-mono text-xs"
                        value={connection.reasoningEffort}
                        onChange={(event) => update({ reasoningEffort: event.target.value })}
                        placeholder={t("detection.llm.roles.inherit")}
                      />
                      <p className="text-xs text-muted-foreground">
                        {t("detection.llm.roles.reasoningEffortHint")}
                      </p>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`llm-${role}-api-key`}>{t("detection.llm.apiKey")}</Label>
                      <div className="flex items-center gap-2">
                        <LampChip
                          tone={keyStatus.configured ? "good" : "neutral"}
                          hollow={!keyStatus.configured}
                        >
                          {keyStatus.configured
                            ? t("detection.llm.apiKeyConfigured", { last4: keyStatus.last4 ?? "" })
                            : t("detection.llm.roles.inherit")}
                        </LampChip>
                      </div>
                      <Input
                        id={`llm-${role}-api-key`}
                        type="password"
                        className="max-w-md"
                        value={connection.apiKeyInput}
                        onChange={(event) => update({ apiKeyInput: event.target.value })}
                        placeholder={t("detection.llm.apiKeyPlaceholder")}
                        autoComplete="off"
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* The chip is the answer; the raw provider/model string underneath is what an
              operator reads out to whoever is helping them, so it is set in the mono face and
              kept on its own line instead of trailing the chip as prose. */}
          <div className="flex flex-col gap-2 rounded-md border border-border bg-muted/40 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="label-channel">{t("detection.llm.connection")}</span>
              {llmHealth && (
                <LampChip {...HEALTH_LAMP[llmHealth.status]}>
                  {t(`detection.llm.health.${llmHealth.status}`)}
                </LampChip>
              )}
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                disabled={checkingLlm}
                onClick={() => void refreshLlmHealth()}
              >
                {checkingLlm ? t("detection.llm.testing") : t("detection.llm.test")}
              </Button>
            </div>
            {llmHealth?.detail && (
              <p className="readout text-[0.6875rem] break-all text-muted-foreground">
                {llmHealth.detail}
              </p>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button variant="brand" size="sm" className="w-fit" onClick={() => void handleSaveLlm()}>
              {t("detection.llm.save")}
            </Button>
            <SaveFeedback error={llmError} saved={llmSaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("detection.alerts.title")}</CardTitle>
          <CardDescription>{t("detection.alerts.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="alert-rate-threshold">{t("detection.alerts.rate")}</Label>
              <Input
                id="alert-rate-threshold"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={alertRateThreshold}
                onChange={(event) => setAlertRateThreshold(Number(event.target.value))}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="alert-window-minutes">{t("detection.alerts.window")}</Label>
              <Input
                id="alert-window-minutes"
                type="number"
                min={1}
                step={1}
                value={alertWindowMinutes}
                onChange={(event) => setAlertWindowMinutes(Number(event.target.value))}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="brand" size="sm" className="w-fit" onClick={() => void handleSaveAlerts()}>
              {t("detection.alerts.save")}
            </Button>
            <SaveFeedback error={alertsError} saved={alertsSaved} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

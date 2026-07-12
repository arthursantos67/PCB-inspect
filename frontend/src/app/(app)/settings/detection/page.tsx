"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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
  getHealth,
  updateConfig,
  type AgentAnalysisMode,
  type HealthCheckResult,
  type LlmProvider,
  type SecretConfigValue,
} from "@/lib/api-client";
import { DEFECT_TYPE_LABEL, DEFECT_TYPES, SEVERITIES, SEVERITY_LABEL } from "@/lib/chart-colors";

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

const AGENT_MODE_LABEL: Record<AgentAnalysisMode, string> = {
  conditional: "Conditional (default)",
  always: "Always",
  on_demand: "On demand",
};

const PROVIDER_LABEL: Record<LlmProvider, string> = {
  openai_compatible: "Local (OpenAI-compatible — LM Studio / Ollama / vLLM)",
  anthropic: "Anthropic (cloud)",
  google: "Google (cloud)",
};

const HEALTH_LABEL: Record<HealthCheckResult["status"], string> = {
  ok: "Reachable",
  error: "Unreachable",
  not_configured: "Not configured",
};

const HEALTH_VARIANT: Record<
  HealthCheckResult["status"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  ok: "default",
  error: "destructive",
  not_configured: "outline",
};

function isSecretConfigValue(value: unknown): value is SecretConfigValue {
  return typeof value === "object" && value !== null && "configured" in value;
}

function SaveFeedback({ error, saved }: { error: string | null; saved: boolean }) {
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (saved) return <p className="text-sm text-muted-foreground">Saved.</p>;
  return null;
}

export default function SettingsDetectionPage() {
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

        if (typeof config.alert_defect_rate_threshold === "number") {
          setAlertRateThreshold(config.alert_defect_rate_threshold);
        }
        if (typeof config.alert_window_minutes === "number") {
          setAlertWindowMinutes(config.alert_window_minutes);
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

  async function refreshLlmHealth() {
    setCheckingLlm(true);
    try {
      const health = await getHealth();
      setLlmHealth(health.llm);
    } catch {
      setLlmHealth({ status: "error", detail: "Failed to reach the backend health check." });
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
      setThresholdsError(err instanceof ApiError ? err.message : "Failed to save thresholds.");
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
      setPolicyError(err instanceof ApiError ? err.message : "Failed to save the analysis policy.");
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

      const { config } = await updateConfig(update);
      if (isSecretConfigValue(config["llm.api_key"])) setApiKeyStatus(config["llm.api_key"]);
      setApiKeyInput("");
      setLlmSaved(true);
      await refreshLlmHealth();
    } catch (err) {
      setLlmError(err instanceof ApiError ? err.message : "Failed to save the LLM connection.");
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
      setAlertsError(err instanceof ApiError ? err.message : "Failed to save alert thresholds.");
    }
  }

  const isCloudProvider = provider !== "openai_compatible";

  return (
    <div className="flex flex-col gap-6">
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Confidence thresholds</CardTitle>
          <CardDescription>
            Detections at or above the store threshold are persisted; only those at or above the
            report threshold are shown in the interface and aggregates (RV-03).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="min-confidence-store">Store threshold</Label>
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
              <Label htmlFor="min-confidence-report">Report threshold</Label>
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
            <Button size="sm" className="w-fit" onClick={() => void handleSaveThresholds()}>
              Save thresholds
            </Button>
            <SaveFeedback error={thresholdsError} saved={thresholdsSaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Agent analysis policy</CardTitle>
          <CardDescription>
            Controls when the Analyst → Reviewer → Summarizer chain runs on top of the always-on
            knowledge-base baseline (FR-06).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="agent-analysis-mode">Mode</Label>
            <Select
              value={agentMode}
              onValueChange={(value) => setAgentMode(value as AgentAnalysisMode)}
            >
              <SelectTrigger id="agent-analysis-mode" className="w-full max-w-md">
                <SelectValue>
                  {(value: AgentAnalysisMode) => AGENT_MODE_LABEL[value]}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(AGENT_MODE_LABEL) as AgentAnalysisMode[]).map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {AGENT_MODE_LABEL[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {agentMode === "conditional" && (
            <div className="flex flex-col gap-4 rounded-lg border p-4">
              <p className="text-sm text-muted-foreground">
                The chain runs when a board has at least N reportable defects, contains a
                configured critical class, or the baseline severity meets the minimum below.
              </p>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="min-defect-count">Minimum reportable defects (N)</Label>
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
                <span className="text-sm font-medium">Critical defect classes</span>
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
                      {DEFECT_TYPE_LABEL[defectType]}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="min-severity">Minimum baseline severity</Label>
                <Select
                  value={minSeverity}
                  onValueChange={(value) => value && setMinSeverity(value)}
                >
                  <SelectTrigger id="min-severity" className="w-full max-w-48">
                    <SelectValue>
                      {(value: string) =>
                        SEVERITY_LABEL[value as keyof typeof SEVERITY_LABEL] ?? value
                      }
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITIES.map((severity) => (
                      <SelectItem key={severity} value={severity}>
                        {SEVERITY_LABEL[severity]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button size="sm" className="w-fit" onClick={() => void handleSavePolicy()}>
              Save policy
            </Button>
            <SaveFeedback error={policyError} saved={policySaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>LLM connection</CardTitle>
          <CardDescription>
            Local-first by default (section 5.2) — no board imagery or defect data leaves the
            machine unless a cloud provider is explicitly selected below.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-provider">Provider</Label>
            <Select value={provider} onValueChange={(value) => setProvider(value as LlmProvider)}>
              <SelectTrigger id="llm-provider" className="w-full max-w-md">
                <SelectValue>{(value: LlmProvider) => PROVIDER_LABEL[value]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(PROVIDER_LABEL) as LlmProvider[]).map((value) => (
                  <SelectItem key={value} value={value}>
                    {PROVIDER_LABEL[value]}
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
              Board images and derived text will be sent to {PROVIDER_LABEL[provider]}. Only
              choose a cloud provider if that is acceptable for this deployment.
            </div>
          )}

          {!isCloudProvider && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="llm-base-url">Base URL</Label>
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
            <Label htmlFor="llm-model">Model</Label>
            <Input
              id="llm-model"
              className="max-w-md"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </div>

          {isCloudProvider && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="llm-api-key">API key</Label>
              <div className="flex items-center gap-2">
                <Badge variant={apiKeyStatus.configured ? "default" : "outline"}>
                  {apiKeyStatus.configured
                    ? `Configured (••••${apiKeyStatus.last4})`
                    : "Not configured"}
                </Badge>
              </div>
              <Input
                id="llm-api-key"
                type="password"
                className="max-w-md"
                value={apiKeyInput}
                onChange={(event) => setApiKeyInput(event.target.value)}
                placeholder="Enter to set or replace — never shown again after saving"
                autoComplete="off"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm-timeout">Timeout (seconds)</Label>
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

          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Connection status:</span>
            {llmHealth && (
              <Badge variant={HEALTH_VARIANT[llmHealth.status]}>
                {HEALTH_LABEL[llmHealth.status]}
              </Badge>
            )}
            {llmHealth?.detail && (
              <span className="text-xs text-muted-foreground">{llmHealth.detail}</span>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={checkingLlm}
              onClick={() => void refreshLlmHealth()}
            >
              Test connection
            </Button>
          </div>

          <div className="flex items-center gap-3">
            <Button size="sm" className="w-fit" onClick={() => void handleSaveLlm()}>
              Save LLM connection
            </Button>
            <SaveFeedback error={llmError} saved={llmSaved} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Quality alert thresholds</CardTitle>
          <CardDescription>
            Defect rate per batch and time window that triggers a quality alert (FR-19).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="alert-rate-threshold">Defect rate threshold</Label>
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
              <Label htmlFor="alert-window-minutes">Time window (minutes)</Label>
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
            <Button size="sm" className="w-fit" onClick={() => void handleSaveAlerts()}>
              Save alert thresholds
            </Button>
            <SaveFeedback error={alertsError} saved={alertsSaved} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

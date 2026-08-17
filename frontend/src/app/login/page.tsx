"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { BrandMark } from "@/components/layout/BrandMark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";
import { useI18n } from "@/contexts/I18nContext";
import { ApiError, getSetupStatus } from "@/lib/api-client";

function LoginForm() {
  const { login, setup, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedNext = searchParams.get("next");
  // Only ever redirect to a same-origin app path — a bare "/"-prefixed string, never
  // "//host/..." (protocol-relative) or an absolute URL, which `next` being attacker-suppliable
  // via a direct /login?next=... link would otherwise turn into an open redirect.
  const nextPath =
    requestedNext && requestedNext.startsWith("/") && !requestedNext.startsWith("//")
      ? requestedNext
      : "/";

  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated) router.replace(nextPath);
  }, [isAuthenticated, nextPath, router]);

  useEffect(() => {
    let cancelled = false;
    getSetupStatus()
      .then((status) => {
        if (!cancelled) setSetupRequired(status.setup_required);
      })
      .catch(() => {
        if (!cancelled) setSetupRequired(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (setupRequired) {
        await setup(email, password, fullName);
      } else {
        await login(email, password);
      }
      router.replace(nextPath);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.unknownError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        {/* The mark and the station line are the whole identity moment: the operator should
            recognise which machine they are at before reading a word of the form. */}
        <div className="mb-6 flex items-center gap-3">
          <BrandMark className="size-9" />
          <div>
            <h1 className="font-heading text-base leading-none font-semibold tracking-[-0.015em]">
              PCB-Inspect
            </h1>
            <p className="label-channel mt-1.5">{t("common.localStation")}</p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{t(setupRequired ? "login.setupTitle" : "login.signInTitle")}</CardTitle>
            <CardDescription>
              {t(setupRequired ? "login.setupDescription" : "login.signInDescription")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              {setupRequired && (
                <div className="field">
                  <Label htmlFor="full_name">{t("login.fullName")}</Label>
                  <Input
                    id="full_name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    required
                    autoComplete="name"
                  />
                </div>
              )}
              <div className="field">
                <Label htmlFor="email">{t("login.email")}</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  autoComplete="email"
                />
              </div>
              <div className="field">
                <Label htmlFor="password">{t("login.password")}</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={10}
                  autoComplete={setupRequired ? "new-password" : "current-password"}
                />
              </div>
              {error && (
                <p
                  className="rounded-md px-3 py-2 text-[0.8125rem] text-status-critical"
                  style={{ boxShadow: "inset 3px 0 0 var(--status-critical)" }}
                >
                  {error}
                </p>
              )}
              <Button
                type="submit"
                variant="brand"
                className="mt-1"
                disabled={submitting || setupRequired === null}
              >
                {t(setupRequired ? "login.createAccount" : "login.submit")}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="mt-5 text-center text-xs text-muted-foreground">
          {t("login.privacyNote")}
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

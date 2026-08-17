"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/contexts/I18nContext";
import {
  type Account,
  ApiError,
  createAccount,
  deleteAccount,
  listAccounts,
  updateAccount,
} from "@/lib/api-client";
import { formatTimestamp } from "@/lib/format";

function NewAccountForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await createAccount({ email: email.trim(), full_name: fullName.trim(), password });
      setEmail("");
      setFullName("");
      setPassword("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("accounts.addFailed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("accounts.new.title")}</CardTitle>
        <CardDescription>{t("accounts.new.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-name">{t("accounts.field.fullName")}</Label>
            <Input
              id="new-account-name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder={t("accounts.placeholder.fullName")}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-email">{t("accounts.field.email")}</Label>
            <Input
              id="new-account-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder={t("accounts.placeholder.email")}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-password">{t("accounts.field.password")}</Label>
            <Input
              id="new-account-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("accounts.placeholder.password")}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            className="w-fit"
            disabled={submitting || !email.trim() || !fullName.trim() || password.length < 10}
            onClick={() => void submit()}
          >
            {t("accounts.add")}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function EditAccountRow({
  account,
  onSaved,
  onCancel,
}: {
  account: Account;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [fullName, setFullName] = useState(account.full_name);
  const [email, setEmail] = useState(account.email);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await updateAccount(account.id, {
        full_name: fullName.trim() !== account.full_name ? fullName.trim() : undefined,
        email: email.trim() !== account.email ? email.trim() : undefined,
        password: password ? password : undefined,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("accounts.updateFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <TableRow>
      <TableCell colSpan={4}>
        <div className="flex flex-col gap-3 py-2">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`edit-name-${account.id}`}>{t("accounts.field.fullName")}</Label>
              <Input
                id={`edit-name-${account.id}`}
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`edit-email-${account.id}`}>{t("accounts.field.email")}</Label>
              <Input
                id={`edit-email-${account.id}`}
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`edit-password-${account.id}`}>
                {t("accounts.field.newPassword")}
              </Label>
              <Input
                id={`edit-password-${account.id}`}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={t("accounts.placeholder.keepPassword")}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={
                saving ||
                !fullName.trim() ||
                !email.trim() ||
                (password.length > 0 && password.length < 10)
              }
              onClick={() => void save()}
            >
              {t("accounts.save")}
            </Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={onCancel}>
              {t("accounts.cancel")}
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        </div>
      </TableCell>
    </TableRow>
  );
}

function RemoveAccountControl({ account, onRemoved }: { account: Account; onRemoved: () => void }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);

  async function remove() {
    setError(null);
    setRemoving(true);
    try {
      await deleteAccount(account.id);
      onRemoved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("accounts.removeFailed"));
      setConfirming(false);
    } finally {
      setRemoving(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="flex gap-2">
          <Button size="sm" variant="destructive" disabled={removing} onClick={() => void remove()}>
            {t("accounts.confirmRemove")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={removing}
            onClick={() => setConfirming(false)}
          >
            {t("accounts.cancel")}
          </Button>
        </div>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
        {t("accounts.remove")}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default function SettingsAccountsPage() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setAccounts(await listAccounts());
      setLoadError(null);
    } catch (err) {
      // The empty string stands for "failed, with nothing specific to say"; the wording is
      // picked at render time so this callback does not depend on the current language.
      setLoadError(err instanceof ApiError ? err.message : "");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col gap-6">
      {loadError !== null && (
        <p className="text-sm text-destructive">{loadError || t("accounts.loadFailed")}</p>
      )}

      <NewAccountForm onCreated={() => void refresh()} />

      <Card>
        <CardHeader>
          <CardTitle>{t("accounts.list.title")}</CardTitle>
          <CardDescription>{t("accounts.list.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("accounts.column.name")}</TableHead>
                <TableHead>{t("accounts.column.email")}</TableHead>
                <TableHead>{t("accounts.column.created")}</TableHead>
                <TableHead>{t("accounts.column.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((account) =>
                editingId === account.id ? (
                  <EditAccountRow
                    key={account.id}
                    account={account}
                    onSaved={() => {
                      setEditingId(null);
                      void refresh();
                    }}
                    onCancel={() => setEditingId(null)}
                  />
                ) : (
                  <TableRow key={account.id}>
                    <TableCell className="font-medium">{account.full_name}</TableCell>
                    <TableCell>{account.email}</TableCell>
                    <TableCell className="readout text-xs whitespace-nowrap text-muted-foreground">
                      {formatTimestamp(account.created_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditingId(account.id)}
                        >
                          {t("accounts.edit")}
                        </Button>
                        <RemoveAccountControl account={account} onRemoved={() => void refresh()} />
                      </div>
                    </TableCell>
                  </TableRow>
                )
              )}
              {accounts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                    {t("accounts.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

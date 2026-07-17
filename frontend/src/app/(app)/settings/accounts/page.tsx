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
import {
  type Account,
  ApiError,
  createAccount,
  deleteAccount,
  listAccounts,
  updateAccount,
} from "@/lib/api-client";

function NewAccountForm({ onCreated }: { onCreated: () => void }) {
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
      setError(err instanceof ApiError ? err.message : "Failed to add this account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add an account</CardTitle>
        <CardDescription>
          Every local account has identical access — there is no role or permission tier
          (FR-02).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-name">Full name</Label>
            <Input
              id="new-account-name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Operator name"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-email">Email</Label>
            <Input
              id="new-account-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="operator@pcb-inspect.local"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-account-password">Password</Label>
            <Input
              id="new-account-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="At least 10 characters"
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
            Add account
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
      setError(err instanceof ApiError ? err.message : "Failed to update this account.");
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
              <Label htmlFor={`edit-name-${account.id}`}>Full name</Label>
              <Input
                id={`edit-name-${account.id}`}
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`edit-email-${account.id}`}>Email</Label>
              <Input
                id={`edit-email-${account.id}`}
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`edit-password-${account.id}`}>New password (optional)</Label>
              <Input
                id={`edit-password-${account.id}`}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Leave blank to keep current"
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
              Save
            </Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={onCancel}>
              Cancel
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        </div>
      </TableCell>
    </TableRow>
  );
}

function RemoveAccountControl({ account, onRemoved }: { account: Account; onRemoved: () => void }) {
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
      setError(
        err instanceof ApiError ? err.message : "Failed to remove this account."
      );
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
            Confirm remove
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={removing}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
        </div>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
        Remove
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default function SettingsAccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setAccounts(await listAccounts());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Failed to load accounts.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col gap-6">
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      <NewAccountForm onCreated={() => void refresh()} />

      <Card>
        <CardHeader>
          <CardTitle>Accounts</CardTitle>
          <CardDescription>
            Every account can add, rename, remove, or change the password of any other — there
            is no administrator tier (PRD section 2.2).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Actions</TableHead>
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
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(account.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditingId(account.id)}
                        >
                          Edit
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
                    No accounts found.
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

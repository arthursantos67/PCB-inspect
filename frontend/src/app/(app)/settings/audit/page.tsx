"use client";

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  AUDIT_ACTION_LABEL,
  AUDIT_ACTIONS,
  type AuditLogEntry,
  listAccounts,
  listAuditLog,
} from "@/lib/api-client";

const PAGE_SIZE = 20;

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function actionLabel(action: string): string {
  return (AUDIT_ACTION_LABEL as Record<string, string>)[action] ?? action;
}

function EntryPayload({ entry }: { entry: AuditLogEntry }) {
  if (!entry.payload || Object.keys(entry.payload).length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <details className="text-xs">
      <summary className="cursor-pointer whitespace-nowrap">Details</summary>
      <pre className="mt-1 max-w-xs overflow-x-auto whitespace-pre-wrap text-muted-foreground">
        {JSON.stringify(entry.payload, null, 2)}
      </pre>
    </details>
  );
}

export default function SettingsAuditPage() {
  const [accountId, setAccountId] = useState("");
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const accountsQuery = useQuery({ queryKey: ["accounts"], queryFn: listAccounts });

  const listQuery = useQuery({
    queryKey: ["audit-log", accountId, action, dateFrom, dateTo, page],
    queryFn: () =>
      listAuditLog({
        account_id: accountId || undefined,
        action: action || undefined,
        // Dates are UTC (PRD section 11.1) — the date-only picker value is treated as a UTC
        // calendar day, matching the convention used by every other date-range filter.
        date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
        date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const total = listQuery.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function applyFilters(next: { accountId?: string; action?: string; from?: string; to?: string }) {
    if (next.accountId !== undefined) setAccountId(next.accountId);
    if (next.action !== undefined) setAction(next.action);
    if (next.from !== undefined) setDateFrom(next.from);
    if (next.to !== undefined) setDateTo(next.to);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Audit log</h1>
        <p className="text-sm text-muted-foreground">
          Every sensitive action (FR-16) is recorded here, append-only, and never editable.
        </p>
      </div>

      <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-filter-account">Account</Label>
            <select
              id="audit-filter-account"
              className={SELECT_CLASS}
              value={accountId}
              onChange={(event) => applyFilters({ accountId: event.target.value })}
            >
              <option value="">All accounts</option>
              {(accountsQuery.data ?? []).map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.full_name} ({acc.email})
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-filter-action">Action</Label>
            <select
              id="audit-filter-action"
              className={SELECT_CLASS}
              value={action}
              onChange={(event) => applyFilters({ action: event.target.value })}
            >
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((value) => (
                <option key={value} value={value}>
                  {AUDIT_ACTION_LABEL[value]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-filter-date-from">From</Label>
            <Input
              id="audit-filter-date-from"
              type="date"
              value={dateFrom}
              onChange={(event) => applyFilters({ from: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-filter-date-to">To</Label>
            <Input
              id="audit-filter-date-to"
              type="date"
              value={dateTo}
              onChange={(event) => applyFilters({ to: event.target.value })}
            />
          </div>
        </div>
        {(accountId || action || dateFrom || dateTo) && (
          <Button
            size="sm"
            variant="ghost"
            className="w-fit"
            onClick={() => applyFilters({ accountId: "", action: "", from: "", to: "" })}
          >
            Clear filters
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Records{listQuery.isSuccess ? ` (${total})` : ""}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Entity</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data?.results ?? []).map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(entry.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    {entry.actor ? (
                      <span>
                        {entry.actor.full_name}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({entry.actor.email})
                        </span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">System</span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{actionLabel(entry.action)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {entry.entity_type}
                    {entry.entity_id ? ` · ${entry.entity_id.slice(0, 8)}…` : ""}
                  </TableCell>
                  <TableCell>
                    <EntryPayload entry={entry} />
                  </TableCell>
                </TableRow>
              ))}
              {listQuery.isSuccess && total === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    No audit records match these filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

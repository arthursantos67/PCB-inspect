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
import { useI18n, type Translate } from "@/contexts/I18nContext";
import {
  AUDIT_ACTIONS,
  type AuditAction,
  type AuditLogEntry,
  listAccounts,
  listAuditLog,
} from "@/lib/api-client";
import { formatTimestampPrecise } from "@/lib/format";

const PAGE_SIZE = 20;

// Shared control shell, see globals.css.
const SELECT_CLASS = "control";

/** An entry written by a newer build can carry an action this one has no wording for, so the
 * raw string is shown rather than a missing key.
 */
function actionLabel(action: string, t: Translate): string {
  return AUDIT_ACTIONS.includes(action as AuditAction)
    ? t(`audit.action.${action as AuditAction}`)
    : action;
}

function EntryPayload({ entry }: { entry: AuditLogEntry }) {
  const { t } = useI18n();
  if (!entry.payload || Object.keys(entry.payload).length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <details className="text-xs">
      <summary className="cursor-pointer whitespace-nowrap">{t("audit.details")}</summary>
      <pre className="mt-1 max-w-xs overflow-x-auto whitespace-pre-wrap text-muted-foreground">
        {JSON.stringify(entry.payload, null, 2)}
      </pre>
    </details>
  );
}

export default function SettingsAuditPage() {
  const { t } = useI18n();
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
        <h2 className="font-heading text-base font-semibold tracking-[-0.012em]">
          {t("audit.title")}
        </h2>
        <p className="mt-1 text-[0.8125rem] text-muted-foreground">{t("audit.description")}</p>
      </div>

      <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 shadow-panel">
        <div className="grid grid-cols-1 gap-x-4 gap-y-3.5 sm:grid-cols-2 lg:grid-cols-4">
          <div className="field">
            <Label htmlFor="audit-filter-account">{t("audit.filter.account")}</Label>
            <select
              id="audit-filter-account"
              className={SELECT_CLASS}
              value={accountId}
              onChange={(event) => applyFilters({ accountId: event.target.value })}
            >
              <option value="">{t("audit.filter.allAccounts")}</option>
              {(accountsQuery.data ?? []).map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.full_name} ({acc.email})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <Label htmlFor="audit-filter-action">{t("audit.filter.action")}</Label>
            <select
              id="audit-filter-action"
              className={SELECT_CLASS}
              value={action}
              onChange={(event) => applyFilters({ action: event.target.value })}
            >
              <option value="">{t("audit.filter.allActions")}</option>
              {AUDIT_ACTIONS.map((value) => (
                <option key={value} value={value}>
                  {t(`audit.action.${value}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <Label htmlFor="audit-filter-date-from">{t("audit.filter.from")}</Label>
            <Input
              id="audit-filter-date-from"
              type="date"
              value={dateFrom}
              onChange={(event) => applyFilters({ from: event.target.value })}
            />
          </div>
          <div className="field">
            <Label htmlFor="audit-filter-date-to">{t("audit.filter.to")}</Label>
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
            {t("audit.filter.clear")}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {t("audit.records")}
            {listQuery.isSuccess ? ` (${total})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("audit.column.when")}</TableHead>
                <TableHead>{t("audit.column.account")}</TableHead>
                <TableHead>{t("audit.column.action")}</TableHead>
                <TableHead>{t("audit.column.entity")}</TableHead>
                <TableHead>{t("audit.column.details")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data?.results ?? []).map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="readout text-xs whitespace-nowrap text-muted-foreground">
                    {formatTimestampPrecise(entry.created_at)}
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
                      <span className="text-muted-foreground">{t("audit.system")}</span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{actionLabel(entry.action, t)}</TableCell>
                  <TableCell className="readout text-xs text-muted-foreground">
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
                    {t("audit.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {t("common.pageOf", { page, total: totalPages })}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => current - 1)}
                >
                  {t("common.previous")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  {t("common.next")}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

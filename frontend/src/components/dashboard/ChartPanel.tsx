"use client";

import { useState } from "react";
import { Maximize2 } from "lucide-react";

import { Dialog, DialogBody, DialogHeader, DialogPopup, DialogTitle } from "@/components/ui/dialog";
import { useI18n } from "@/contexts/I18nContext";
import { cn } from "@/lib/utils";

/** The dashboard's four measurements live in one bezel, quartered by hairline seams — a
 * four-window instrument face rather than four cards adrift in a gutter. Panels are sized
 * for a glance; every one of them opens to a full-size read with a data table beneath it,
 * which is also how the charts satisfy the "a table view exists" requirement without
 * spending dashboard space on one.
 */
export function ChartGrid({
  children,
  footer,
}: {
  children: React.ReactNode;
  /** Controls shared by more than one window, seated inside the same bezel so their scope
   *  reads as "this instrument" rather than "the page". */
  footer?: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border shadow-panel lg:grid-cols-2">
      {children}
      {footer ? <div className="bg-card lg:col-span-2">{footer}</div> : null}
    </div>
  );
}

export function ChartPanel({
  channel,
  title,
  description,
  headline,
  toolbar,
  detail,
  children,
}: {
  /** Engraved label naming what this window measures ("over time", "by class"). */
  channel: string;
  title: string;
  /** One line, shown in the expanded read, saying how to interpret the chart. */
  description: string;
  /** Compact readout pinned to the panel's top-right — the number the chart is about. */
  headline?: React.ReactNode;
  /** Controls that stay usable without expanding (period selector, series toggles). */
  toolbar?: React.ReactNode;
  /** Extra content shown only when expanded: the underlying numbers as a table. */
  detail?: React.ReactNode;
  /** Rendered twice: compact in the panel, and again at full size in the dialog. */
  children: (expanded: boolean) => React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();

  return (
    <>
      <section className="group/panel relative flex min-w-0 flex-col bg-card transition-colors">
        {/* Copper hairline along the top edge on hover: the panel under the cursor is the
            one that will open, signalled without moving anything. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-brand opacity-0 transition-opacity duration-200 group-hover/panel:opacity-100"
        />

        <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0">
            <p className="label-channel">{channel}</p>
            <h3 className="mt-1.5 font-heading text-[0.9375rem] leading-none font-semibold tracking-[-0.012em]">
              {title}
            </h3>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {headline}
            {toolbar}
            <button
              type="button"
              onClick={() => setExpanded(true)}
              aria-label={t("chart.expand", { title })}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover/panel:opacity-100"
            >
              <Maximize2 className="size-3.5" />
            </button>
          </div>
        </div>

        {/* The chart itself is the expand target: clicking anywhere on the plot opens it. */}
        <div
          role="button"
          tabIndex={0}
          aria-label={t("chart.expand", { title })}
          onClick={() => setExpanded(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setExpanded(true);
            }
          }}
          className="flex-1 cursor-zoom-in px-2 pb-4 focus-visible:outline-offset-[-2px]"
        >
          {children(false)}
        </div>
      </section>

      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogPopup className="max-w-5xl">
          <DialogHeader>
            <p className="label-channel">{channel}</p>
            <DialogTitle className="mt-1">{title}</DialogTitle>
            <p className="text-[0.8125rem] text-muted-foreground">{description}</p>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-6">
            {toolbar ? <div className="flex flex-wrap items-center gap-2">{toolbar}</div> : null}
            {children(true)}
            {detail}
          </DialogBody>
        </DialogPopup>
      </Dialog>
    </>
  );
}

/** Shared empty/error/loading state for a panel's plot area, so all four windows fail the
 * same way instead of each inventing its own message.
 */
export function ChartPlaceholder({
  isLoading,
  isError,
  emptyMessage,
  className,
}: {
  isLoading?: boolean;
  isError?: boolean;
  emptyMessage: string;
  className?: string;
}) {
  const { t } = useI18n();

  return (
    <p
      className={cn(
        "flex h-full items-center justify-center px-4 text-center text-[0.8125rem] text-muted-foreground",
        className
      )}
    >
      {isError ? t("chart.loadFailed") : isLoading ? t("chart.loading") : emptyMessage}
    </p>
  );
}

/** The numbers behind a chart, shown in the expanded read. Identity keeps its color chip so
 * the table and the plot are read as the same thing.
 */
export function ChartDataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: readonly string[];
  rows: readonly { key: string; color?: string; cells: readonly React.ReactNode[] }[];
}) {
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <table className="w-full text-sm">
        <caption className="label-channel border-b border-border bg-muted/40 px-3 py-2 text-left">
          {caption}
        </caption>
        <thead>
          <tr className="border-b border-border">
            {columns.map((column, index) => (
              <th
                key={column}
                scope="col"
                className={cn(
                  "label-channel px-3 py-2",
                  index === 0 ? "text-left" : "text-right"
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-border last:border-0">
              {row.cells.map((cell, index) => (
                <td
                  key={index}
                  className={cn(
                    "px-3 py-2",
                    index === 0 ? "text-left" : "readout text-right"
                  )}
                >
                  {index === 0 && row.color ? (
                    <span className="inline-flex items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="size-2 shrink-0 rounded-[2px]"
                        style={{ backgroundColor: row.color }}
                      />
                      {cell}
                    </span>
                  ) : (
                    cell
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

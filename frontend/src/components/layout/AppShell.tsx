"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Cpu,
  FileText,
  FolderInput,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  ScanLine,
  Settings,
  type LucideIcon,
} from "lucide-react";

import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { BrandMark } from "@/components/layout/BrandMark";
import { useAuth } from "@/contexts/AuthContext";
import { useI18n } from "@/contexts/I18nContext";
import { type EventStreamStatus, useEventStream } from "@/hooks/useEventStream";
import type { TranslationKey } from "@/lib/i18n/types";

type NavItem = { labelKey: TranslationKey; href: string; icon: LucideIcon };

/** Grouped by what the operator is doing, not by which module owns the route: the floor
 * (boards moving through the line), the analysis on top of it, and the machine's own
 * configuration. Seven flat links gave no such reading.
 */
const NAV_GROUPS: { labelKey: TranslationKey; items: readonly NavItem[] }[] = [
  {
    labelKey: "shell.navGroup.line",
    items: [
      { labelKey: "nav.dashboard", href: "/", icon: LayoutDashboard },
      { labelKey: "nav.inspections", href: "/inspections", icon: ScanLine },
      { labelKey: "nav.ingestion", href: "/ingestion", icon: FolderInput },
    ],
  },
  {
    labelKey: "shell.navGroup.analysis",
    items: [
      { labelKey: "nav.chat", href: "/chat", icon: MessageSquareText },
      { labelKey: "nav.reports", href: "/reports", icon: FileText },
      { labelKey: "nav.model", href: "/model", icon: Cpu },
    ],
  },
  {
    labelKey: "shell.navGroup.system",
    items: [{ labelKey: "nav.settings", href: "/settings/ingestion", icon: Settings }],
  },
];

const STATUS_TEXT: Record<EventStreamStatus, TranslationKey> = {
  connecting: "shell.status.connecting",
  connected: "shell.status.connected",
  reconnecting: "shell.status.reconnecting",
  disconnected: "shell.status.disconnected",
};

const STATUS_DETAIL: Record<EventStreamStatus, TranslationKey> = {
  connecting: "shell.statusDetail.connecting",
  connected: "shell.statusDetail.connected",
  reconnecting: "shell.statusDetail.reconnecting",
  disconnected: "shell.statusDetail.disconnected",
};

const STATUS_TONE: Record<EventStreamStatus, string> = {
  connecting: "var(--status-warning)",
  connected: "var(--status-good)",
  reconnecting: "var(--status-warning)",
  disconnected: "var(--muted-foreground)",
};

/** Indicator lamp, read the way a lamp on a machine is read: a lit dot with its state
 * spelled out beside it. Only the connected state breathes, so movement means "receiving".
 */
function LiveStatusLamp({ status }: { status: EventStreamStatus }) {
  const { t } = useI18n();
  const tone = STATUS_TONE[status];
  return (
    <div
      className="flex items-center gap-2 px-2"
      title={t(STATUS_DETAIL[status])}
      aria-live="polite"
    >
      <span className="relative flex size-2 shrink-0 items-center justify-center">
        {status === "connected" && (
          <span
            aria-hidden="true"
            className="absolute size-2 animate-ping rounded-full opacity-60 [animation-duration:2.4s]"
            style={{ backgroundColor: tone }}
          />
        )}
        <span
          aria-hidden="true"
          className="relative size-2 rounded-full"
          style={{ backgroundColor: tone }}
        />
      </span>
      <span className="label-channel">
        <span className="sr-only">{t("shell.liveUpdates")}</span>
        {t(STATUS_TEXT[status])}
      </span>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const eventStreamStatus = useEventStream(isAuthenticated);
  const pathname = usePathname();

  function isActive(item: NavItem) {
    if (item.href === "/") return pathname === "/";
    if (item.labelKey === "nav.settings") return pathname.startsWith("/settings");
    return pathname.startsWith(item.href);
  }

  return (
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-3 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground"
      >
        {t("shell.skipToContent")}
      </a>

      <aside className="sticky top-0 flex h-screen w-[15rem] shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-6">
          <BrandMark className="size-7 text-primary-foreground" />
          <span className="flex min-w-0 flex-col leading-none">
            <span className="font-heading text-[0.9375rem] font-semibold tracking-[-0.01em]">
              PCB-Inspect
            </span>
            <span className="label-channel mt-1">{t("common.localStation")}</span>
          </span>
        </div>

        <nav
          aria-label={t("shell.primaryNav")}
          className="flex flex-1 flex-col gap-6 overflow-y-auto px-3"
        >
          {NAV_GROUPS.map((group) => (
            <div key={group.labelKey} className="flex flex-col gap-1">
              <p className="label-channel px-2 pb-1.5">{t(group.labelKey)}</p>
              {group.items.map((item) => {
                const active = isActive(item);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`group relative flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[0.8125rem] transition-colors ${
                      active
                        ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-panel"
                        : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                    }`}
                  >
                    {/* Copper tick on the active route: the accent marks position, nothing else. */}
                    <span
                      aria-hidden="true"
                      className={`absolute top-1/2 -left-3 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-brand transition-opacity ${
                        active ? "opacity-100" : "opacity-0"
                      }`}
                    />
                    <Icon
                      className={`size-4 shrink-0 transition-colors ${
                        active ? "text-brand" : "text-muted-foreground/70 group-hover:text-foreground"
                      }`}
                    />
                    {t(item.labelKey)}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="mt-6 flex flex-col gap-3 border-t border-sidebar-border px-3 py-3">
          <LiveStatusLamp status={eventStreamStatus} />
          <LanguageSwitcher />
          <div className="flex items-center justify-between gap-2 rounded-md px-2">
            <span className="min-w-0 truncate text-[0.8125rem] text-muted-foreground">
              {user?.full_name ?? t("shell.localAccount")}
            </span>
            <button
              type="button"
              onClick={logout}
              title={t("shell.logOut")}
              className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
            >
              <LogOut className="size-4" />
              <span className="sr-only">{t("shell.logOut")}</span>
            </button>
          </div>
        </div>
      </aside>

      <main
        id="main-content"
        tabIndex={-1}
        className="min-w-0 flex-1 px-8 py-7 outline-none xl:px-10"
      >
        <div className="mx-auto w-full max-w-[1560px]">{children}</div>
      </main>
    </div>
  );
}

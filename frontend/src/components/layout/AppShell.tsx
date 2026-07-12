"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/contexts/AuthContext";
import { type EventStreamStatus, useEventStream } from "@/hooks/useEventStream";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "Inspections", href: "/inspections" },
  { label: "Ingestion", href: "/ingestion" },
  { label: "Chat", href: "/chat" },
  { label: "Reports", href: "/reports" },
  { label: "Settings", href: "/settings/ingestion" },
] as const;

const STATUS_LABEL: Record<EventStreamStatus, string> = {
  connecting: "live updates: connecting…",
  connected: "live updates: connected",
  reconnecting: "live updates: reconnecting…",
  disconnected: "live updates: not connected",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout, isAuthenticated } = useAuth();
  const eventStreamStatus = useEventStream(isAuthenticated);
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-2 focus-visible:top-2 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-3 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground"
      >
        Skip to main content
      </a>
      <aside className="flex w-56 flex-col border-r bg-muted/30 p-4">
        <span className="mb-6 px-2 text-lg font-semibold">PCB-Inspect</span>
        <nav aria-label="Primary" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : item.label === "Settings"
                  ? pathname.startsWith("/settings")
                  : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`rounded-md px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground ${
                  isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <Badge
            variant={eventStreamStatus === "connected" ? "default" : "outline"}
            aria-live="polite"
          >
            {STATUS_LABEL[eventStreamStatus]}
          </Badge>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              {user?.full_name ?? "local account"}
            </span>
            <Button variant="ghost" size="sm" onClick={logout}>
              Log out
            </Button>
          </div>
        </header>
        <Separator />
        <main id="main-content" tabIndex={-1} className="flex-1 p-6 outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}

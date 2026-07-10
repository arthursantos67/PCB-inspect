"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/contexts/AuthContext";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "Inspections", href: "/inspections" },
  { label: "Ingestion", href: "/ingestion" },
  { label: "Chat", href: "/chat" },
  { label: "Reports", href: "/reports" },
  { label: "Settings", href: "/settings/accounts" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 flex-col border-r bg-muted/30 p-4">
        <span className="mb-6 px-2 text-lg font-semibold">PCB-Inspect</span>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <Badge variant="outline">live updates: not connected</Badge>
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
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

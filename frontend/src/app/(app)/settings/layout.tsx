"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SETTINGS_NAV_ITEMS = [
  { label: "Ingestion", href: "/settings/ingestion" },
  { label: "Detection & Analysis", href: "/settings/detection" },
  { label: "Models", href: "/settings/models" },
] as const;

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Change runtime configuration — no redeploy or restart required (FR-13).
        </p>
      </div>
      <nav aria-label="Settings sections" className="flex gap-1 border-b">
        {SETTINGS_NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={`rounded-t-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}

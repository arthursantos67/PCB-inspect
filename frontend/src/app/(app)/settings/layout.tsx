"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { useI18n } from "@/contexts/I18nContext";

// Only the tab order and their routes live here; the words come from the dictionaries, keyed
// by the section name.
const SETTINGS_NAV_ITEMS = [
  { key: "accounts", href: "/settings/accounts" },
  { key: "ingestion", href: "/settings/ingestion" },
  { key: "detection", href: "/settings/detection" },
  { key: "models", href: "/settings/models" },
  { key: "audit", href: "/settings/audit" },
] as const;

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t("settings.eyebrow")}
        title={t("settings.title")}
        description={t("settings.description")}
      />

      {/* The active section is marked by a copper rule sitting on the same hairline that
          separates the tabs from their content, so the tab reads as physically attached to
          the panel below it. */}
      <nav
        aria-label={t("settings.navLabel")}
        className="-mb-px flex flex-wrap gap-x-1 border-b border-border"
      >
        {SETTINGS_NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-[0.8125rem] font-medium transition-colors ${
                isActive
                  ? "border-brand text-foreground"
                  : "border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground"
              }`}
            >
              {t(`settings.nav.${item.key}`)}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}

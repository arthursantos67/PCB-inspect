"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/contexts/AuthContext";

function AuthedShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!isAuthenticated) {
      // Include the query string, not just the path — a shareable/bookmarked link with
      // filter state (FE-04) must survive the login round trip, not just the route itself.
      const query = searchParams.toString();
      const target = `${pathname || "/"}${query ? `?${query}` : ""}`;
      router.replace(`/login?next=${encodeURIComponent(target)}`);
    }
  }, [isAuthenticated, pathname, searchParams, router]);

  if (!isAuthenticated) return null;

  return <AppShell>{children}</AppShell>;
}

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense>
      <AuthedShell>{children}</AuthedShell>
    </Suspense>
  );
}

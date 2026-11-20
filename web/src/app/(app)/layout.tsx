"use client";

import { SWRConfig } from "swr";
import { AuthGate } from "@/components/auth";
import { AppShell } from "@/components/app-shell";
import { fetcher } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, revalidateOnFocus: false }}>
      <AuthGate>
        <AppShell>{children}</AppShell>
      </AuthGate>
    </SWRConfig>
  );
}

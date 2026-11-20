"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  AudioLines, BarChart3, ClipboardCheck, FileSpreadsheet, History, ListChecks, LogOut, Menu, Phone,
  Settings, Upload, Users, Wrench, X,
} from "lucide-react";
import useSWR, { mutate } from "swr";
import { api, fetcher, type Dashboard } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuth } from "./auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/review", label: "Review queue", icon: ClipboardCheck, badge: true },
  { href: "/calls", label: "Calls", icon: Phone },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/reports", label: "Reports & exports", icon: FileSpreadsheet },
  { href: "/scorecards", label: "Scorecards", icon: ListChecks },
];
const ADMIN_NAV = [
  { href: "/users", label: "Users & API keys", icon: Users },
  { href: "/jobs", label: "Processing jobs", icon: Wrench },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/audit", label: "Audit log", icon: History },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isAdmin } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { data } = useSWR<Dashboard>("/dashboard", fetcher, { refreshInterval: 60_000 });
  const pending = data?.kpis.pending_review ?? 0;

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    // Drop every cached response so the next user starts clean.
    await mutate(() => true, undefined, { revalidate: false });
    router.replace("/login");
  }

  const link = (item: (typeof NAV)[number]) => {
    const active = pathname === item.href || pathname.startsWith(item.href + "/");
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => setOpen(false)}
        className={cn(
          "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
          active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        <Icon className="size-4" />
        <span className="flex-1">{item.label}</span>
        {"badge" in item && item.badge && pending > 0 && (
          <span className="rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">{pending}</span>
        )}
      </Link>
    );
  };

  const sidebar = (
    <div className="flex h-full flex-col gap-4 p-3">
      <Link href="/dashboard" className="flex items-center gap-2 px-2 pt-1">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <AudioLines className="size-4" />
        </span>
        <span className="leading-tight">
          <span className="block text-sm font-semibold">Sauti QA</span>
          <span className="block text-[11px] text-muted-foreground">Call quality assurance</span>
        </span>
      </Link>
      <nav className="flex flex-col gap-0.5">{NAV.map(link)}</nav>
      {isAdmin && (
        <div className="flex flex-col gap-0.5">
          <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Admin</div>
          {ADMIN_NAV.map(link)}
        </div>
      )}
      <div className="mt-auto rounded-lg border bg-card p-2.5">
        <div className="truncate text-sm font-medium">{user.name}</div>
        <div className="truncate text-xs text-muted-foreground">{user.email} · {user.role}</div>
        <button onClick={logout} className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer">
          <LogOut className="size-3.5" /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="hidden border-r bg-muted/30 lg:block lg:sticky lg:top-0 lg:h-screen">{sidebar}</aside>
      <header className="sticky top-0 z-30 flex items-center justify-between border-b bg-card/90 px-4 py-2 backdrop-blur lg:hidden">
        <span className="flex items-center gap-2 text-sm font-semibold"><AudioLines className="size-4 text-primary" /> Sauti QA</span>
        <button onClick={() => setOpen(true)} aria-label="Open menu" className="p-1"><Menu className="size-5" /></button>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64 bg-background shadow-xl">
            <button onClick={() => setOpen(false)} className="absolute right-3 top-3 p-1" aria-label="Close menu"><X className="size-4" /></button>
            {sidebar}
          </div>
        </div>
      )}
      <main className="min-w-0">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b bg-card/50 px-4 py-4 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

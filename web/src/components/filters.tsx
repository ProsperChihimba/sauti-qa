"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { X } from "lucide-react";
import type { Agent } from "@/lib/api";
import { todayEAT } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const ALL = "__all";

export const FILTER_KEYS = ["date_from", "date_to", "agent_id", "queue", "q", "review_status", "status", "auto_fail", "flagged", "passed"];

/** Current filter values from the URL (also used to build API query strings). */
export function useFilters(): Record<string, string> {
  const sp = useSearchParams();
  const out: Record<string, string> = {};
  for (const k of FILTER_KEYS) {
    const v = sp.get(k);
    if (v) out[k] = v;
  }
  return out;
}

export function useSetParams() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  return (changes: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === undefined || v === "" || v === ALL) next.delete(k);
      else next.set(k, v);
    }
    if (!("page" in changes)) next.delete("page");
    const s = next.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  };
}

const PRESETS: { label: string; from: () => string; to: () => string }[] = [
  { label: "Today", from: () => todayEAT(), to: () => todayEAT() },
  { label: "7 days", from: () => todayEAT(-6), to: () => todayEAT() },
  { label: "30 days", from: () => todayEAT(-29), to: () => todayEAT() },
];

export function FilterBar({ extra, search = false }: { extra?: React.ReactNode; search?: boolean }) {
  const f = useFilters();
  const set = useSetParams();
  const { data: agents } = useSWR<Agent[]>("/agents");
  const { data: queues } = useSWR<string[]>("/queues");
  const active = Object.keys(f).length > 0;

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex items-center gap-1">
        {PRESETS.map((p) => (
          <Button
            key={p.label}
            size="sm"
            variant={f.date_from === p.from() && f.date_to === p.to() ? "secondary" : "ghost"}
            onClick={() => set({ date_from: p.from(), date_to: p.to() })}
          >
            {p.label}
          </Button>
        ))}
      </div>
      <Input type="date" aria-label="From date" className="h-8 w-[9.5rem] text-xs" value={f.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value })} />
      <span className="pb-1.5 text-xs text-muted-foreground">to</span>
      <Input type="date" aria-label="To date" className="h-8 w-[9.5rem] text-xs" value={f.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value })} />
      <Select value={f.agent_id ?? ALL} onValueChange={(v) => set({ agent_id: v })}>
        <SelectTrigger className="h-8 w-40 text-xs" aria-label="Agent"><SelectValue placeholder="All agents" /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All agents</SelectItem>
          {agents?.map((a) => <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={f.queue ?? ALL} onValueChange={(v) => set({ queue: v })}>
        <SelectTrigger className="h-8 w-36 text-xs" aria-label="Queue"><SelectValue placeholder="All queues" /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All queues</SelectItem>
          {queues?.map((q) => <SelectItem key={q} value={q}>{q}</SelectItem>)}
        </SelectContent>
      </Select>
      {search && (
        <Input
          key={f.q ?? ""}
          placeholder="Search transcript, agent, file..."
          className="h-8 w-56 text-xs"
          defaultValue={f.q ?? ""}
          onKeyDown={(e) => { if (e.key === "Enter") set({ q: (e.target as HTMLInputElement).value }); }}
          onBlur={(e) => { if (e.target.value !== (f.q ?? "")) set({ q: e.target.value }); }}
        />
      )}
      {extra}
      {active && (
        <Button size="sm" variant="ghost" onClick={() => set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}>
          <X /> Clear
        </Button>
      )}
    </div>
  );
}

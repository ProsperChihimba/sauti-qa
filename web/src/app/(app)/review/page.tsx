"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { PlayCircle } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { CallTable } from "@/components/call-table";
import { FilterBar, useFilters, useSetParams } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, qs, type CallListItem, type Page } from "@/lib/api";

function Queue() {
  const f = useFilters();
  const sp = useSearchParams();
  const set = useSetParams();
  const page = Number(sp.get("page") ?? 1);
  const { data } = useSWR<Page<CallListItem>>(`/review/queue${qs({ ...f, page, page_size: 25 })}`, { refreshInterval: 15000 });
  return (
    <>
      <div className="border-b px-4 py-2.5 sm:px-6"><FilterBar /></div>
      <div className="p-4 sm:p-6">
        <p className="mb-3 text-sm text-muted-foreground">
          Calls are sent here when they fail a critical item, are flagged, score below the threshold or the AI is unsure.
          Most urgent first.
        </p>
        <Card>{data ? <CallTable page={data} showReasons onPage={(p) => set({ page: String(p) })} /> : <Skeleton className="m-4 h-64" />}</Card>
      </div>
    </>
  );
}

function StartButton() {
  const router = useRouter();
  const f = useFilters();
  const [busy, setBusy] = useState(false);
  async function start() {
    setBusy(true);
    try {
      const r = await api<{ call_id: string } | undefined>(`/review/next${qs(f)}`, { method: "POST" });
      if (r?.call_id) router.push(`/calls/${r.call_id}?review=1`);
      else toast.success("The review queue is empty.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <Button onClick={start} disabled={busy}><PlayCircle /> Start reviewing</Button>;
}

export default function ReviewPage() {
  return (
    <Suspense>
      <PageHeader title="Review queue" description="Calls that need a human decision" actions={<StartButton />} />
      <Queue />
    </Suspense>
  );
}

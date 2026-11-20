"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { RotateCcw } from "lucide-react";
import { AdminOnly } from "@/components/admin-only";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, qs, type Job, type Page } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/format";

const VARIANT: Record<string, "secondary" | "default" | "success" | "destructive"> = { queued: "secondary", running: "default", succeeded: "success", failed: "destructive" };

export default function JobsPage() {
  const [status, setStatus] = useState("failed");
  const { data, mutate } = useSWR<Page<Job>>(`/jobs${qs({ status: status === "all" ? undefined : status, page_size: 100 })}`, { refreshInterval: 5000 });
  const { data: summary } = useSWR<Record<string, Record<string, number>>>("/jobs/summary", { refreshInterval: 5000 });

  async function retry(j: Job) {
    try {
      await api(`/jobs/${j.id}/retry`, { method: "POST" });
      toast.success("Re-queued");
      void mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function recover() {
    const r = await api<{ recovered: number[] }>("/jobs/recover", { method: "POST" });
    toast.success(`${r.recovered.length} stuck jobs re-queued`);
    void mutate();
  }

  return (
    <>
      <PageHeader title="Processing jobs" description="Pipeline stages per call. Failed jobs can be retried; stuck jobs are recovered automatically every 5 minutes."
        actions={<Button variant="outline" onClick={recover}><RotateCcw /> Recover stuck jobs now</Button>} />
      <AdminOnly>
        <div className="grid grid-cols-1 gap-4 p-4 sm:p-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {["prepare", "transcribe", "label", "score"].map((k) => (
              <Card key={k} className="p-4">
                <div className="text-xs font-medium text-muted-foreground">{humanize(k)}</div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                  {Object.entries(summary?.[k] ?? {}).map(([s, n]) => <Badge key={s} variant={VARIANT[s]}>{n} {s}</Badge>)}
                </div>
              </Card>
            ))}
          </div>
          <Tabs value={status} onValueChange={setStatus}>
            <TabsList>{["failed", "running", "queued", "all"].map((s) => <TabsTrigger key={s} value={s}>{humanize(s)}</TabsTrigger>)}</TabsList>
          </Tabs>
          <Card>
            <CardContent className="px-2 pt-2">
              <Table>
                <THead><TR><TH>Stage</TH><TH>Call</TH><TH>Status</TH><TH className="text-right">Attempts</TH><TH>Updated</TH><TH>Error</TH><TH /></TR></THead>
                <TBody>
                  {data?.items.map((j) => (
                    <TR key={j.id}>
                      <TD>{humanize(j.kind)} <span className="text-xs text-muted-foreground">({j.queue})</span></TD>
                      <TD>{j.call_id ? <Link className="font-mono text-xs hover:underline" href={`/calls/${j.call_id}`}>{j.call_id.slice(0, 8)}</Link> : "-"}</TD>
                      <TD><Badge variant={VARIANT[j.status]}>{j.status}</Badge></TD>
                      <TD className="text-right tabular-nums">{j.attempts}</TD>
                      <TD className="text-muted-foreground whitespace-nowrap">{fmtDateTime(j.updated_at)}</TD>
                      <TD className="max-w-md"><span className="line-clamp-2 font-mono text-xs text-destructive" title={j.error ?? ""}>{j.error?.split("\n")[0]}</span></TD>
                      <TD className="text-right">{j.status === "failed" && j.call_id && <Button size="sm" variant="outline" onClick={() => retry(j)}>Retry</Button>}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {data?.items.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">Nothing here.</p>}
            </CardContent>
          </Card>
        </div>
      </AdminOnly>
    </>
  );
}

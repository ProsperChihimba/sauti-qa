"use client";

import { Suspense } from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { FilterBar, useFilters } from "@/components/filters";
import { HBars, ShareBar, TrendChart } from "@/components/charts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { qs, type Dashboard } from "@/lib/api";
import { fmtScore } from "@/lib/format";

function Kpi({ label, value, hint, href, tone }: { label: string; value: React.ReactNode; hint?: string; href?: string; tone?: "bad" }) {
  const body = (
    <Card className="h-full p-4 transition-colors hover:border-primary/40">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums tracking-tight ${tone === "bad" ? "text-destructive" : ""}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

function DashboardBody() {
  const f = useFilters();
  const query = qs(f);
  const { data, isLoading } = useSWR<Dashboard>(`/dashboard${query}`, { refreshInterval: 30_000 });

  if (isLoading || !data)
    return (
      <div className="grid grid-cols-1 gap-4 p-4 sm:p-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
        <Skeleton className="h-72" />
      </div>
    );

  const k = data.kpis;
  const weakest = data.criteria.filter((c) => c.pass_rate !== null).slice(0, 8);
  return (
    <div className="grid grid-cols-1 gap-4 p-4 sm:p-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Calls evaluated" value={k.calls_evaluated.toLocaleString()} hint={`${k.processing} processing${k.failed_processing ? ` · ${k.failed_processing} failed` : ""}`} href={`/calls${query}`} />
        <Kpi label="Minutes analysed" value={k.minutes.toLocaleString()} hint="100% call coverage" />
        <Kpi label="Average score" value={fmtScore(k.avg_score)} />
        <Kpi label="Pass rate" value={k.pass_rate == null ? "-" : `${k.pass_rate}%`} />
        <Kpi label="Critical breaches" value={k.critical_breaches} tone={k.critical_breaches ? "bad" : undefined}
          hint={`${k.flagged} calls flagged`} href={`/calls${qs({ ...f, auto_fail: "true" })}`} />
        <Kpi label="Pending review" value={k.pending_review} hint={`${k.reviewed} reviewed · ${k.review_rate ?? 0}% routed`} href="/review" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Quality trend</CardTitle>
            <CardDescription>Daily average score and pass rate (East Africa Time)</CardDescription>
          </CardHeader>
          <CardContent>
            {data.trend.length ? <TrendChart data={data.trend} /> : <p className="py-16 text-center text-sm text-muted-foreground">No calls in this period</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Weakest criteria</CardTitle>
            <CardDescription>Share of applicable calls where the agent met the criterion</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {weakest.map((c) => (
              <div key={c.criterion_id} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="flex min-w-0 items-center gap-1 truncate">
                    {c.critical && <ShieldAlert className="size-3 shrink-0 text-destructive" aria-label="Critical" />}
                    <span className="truncate">{c.label}</span>
                  </span>
                  <span className="tabular-nums font-medium">{c.pass_rate}%</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-muted">
                  <div className="h-1.5 rounded-full bg-[var(--chart-1)]" style={{ width: `${c.pass_rate}%` }} />
                </div>
              </div>
            ))}
            {!weakest.length && <p className="text-sm text-muted-foreground">No scored calls yet</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Agent leaderboard</CardTitle>
            <CardDescription>Sorted by average score</CardDescription>
          </CardHeader>
          <CardContent className="px-2">
            <Table>
              <THead>
                <TR><TH>#</TH><TH>Agent</TH><TH className="text-right">Calls</TH><TH className="text-right">Minutes</TH><TH>Average score</TH><TH className="text-right">Pass rate</TH><TH className="text-right">Critical</TH></TR>
              </THead>
              <TBody>
                {data.agents.map((a, i) => (
                  <TR key={a.agent_id ?? "none"}>
                    <TD className="text-muted-foreground tabular-nums">{i + 1}</TD>
                    <TD className="font-medium">
                      {a.agent_id ? <Link className="hover:underline" href={`/calls${qs({ ...f, agent_id: a.agent_id })}`}>{a.agent}</Link> : a.agent}
                    </TD>
                    <TD className="text-right tabular-nums">{a.calls}</TD>
                    <TD className="text-right tabular-nums">{a.minutes}</TD>
                    <TD>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-24 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-[var(--chart-1)]" style={{ width: `${a.avg_score ?? 0}%` }} /></div>
                        <span className="tabular-nums text-xs">{fmtScore(a.avg_score)}</span>
                      </div>
                    </TD>
                    <TD className="text-right tabular-nums">{a.pass_rate == null ? "-" : `${a.pass_rate}%`}</TD>
                    <TD className="text-right tabular-nums">
                      {a.critical_breaches ? <span className="inline-flex items-center gap-1 text-destructive"><AlertTriangle className="size-3" />{a.critical_breaches}</span> : 0}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {!data.agents.length && <p className="p-4 text-sm text-muted-foreground">No calls yet</p>}
          </CardContent>
        </Card>
        <div className="grid grid-cols-1 gap-4">
          <Card>
            <CardHeader><CardTitle>Resolution</CardTitle></CardHeader>
            <CardContent><ShareBar kind="resolution" data={data.resolution} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Customer sentiment</CardTitle><CardDescription>At the end of the call</CardDescription></CardHeader>
            <CardContent><ShareBar kind="sentiment" data={data.sentiment} /></CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Call reasons</CardTitle><CardDescription>Number of evaluated calls</CardDescription></CardHeader>
        <CardContent>
          {data.call_reasons.length ? <HBars data={data.call_reasons.slice(0, 12).map((r) => ({ name: r.name, value: r.count }))} /> : <p className="text-sm text-muted-foreground">No data</p>}
        </CardContent>
      </Card>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense>
      <PageHeader title="Dashboard" description="Quality across every call, scored automatically" />
      <div className="border-b px-4 py-2.5 sm:px-6"><FilterBar /></div>
      <DashboardBody />
    </Suspense>
  );
}

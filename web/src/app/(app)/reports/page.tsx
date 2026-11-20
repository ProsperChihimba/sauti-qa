"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { AudioLines, Download, FileSpreadsheet, FileText, Loader2 } from "lucide-react";
import { useAuth } from "@/components/auth";
import { PageHeader } from "@/components/app-shell";
import { FilterBar, useFilters } from "@/components/filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type ExportRow } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

function toFilters(f: Record<string, string>) {
  return {
    date_from: f.date_from, date_to: f.date_to,
    agent_ids: f.agent_id ? [Number(f.agent_id)] : [], queues: f.queue ? [f.queue] : [],
  };
}

function Exports() {
  const { isAdmin } = useAuth();
  const f = useFilters();
  const [busy, setBusy] = useState<string | null>(null);
  const [includeReviewed, setIncludeReviewed] = useState(false);
  const [testFraction, setTestFraction] = useState(0.1);
  const { data, mutate } = useSWR<ExportRow[]>("/exports", {
    refreshInterval: (d) => (d?.some((e) => e.status === "queued" || e.status === "running") ? 2000 : 0),
  });

  async function run(kind: "excel" | "csv" | "dataset") {
    setBusy(kind);
    try {
      await api("/exports", { method: "POST", json: { kind, filters: toFilters(f), include_unedited_reviewed: includeReviewed, test_fraction: testFraction } });
      toast.success("Export started. It appears below when ready.");
      void mutate();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const describe = (e: ExportRow) => {
    const fl = e.filters as Record<string, unknown>;
    const period = fl.date_from || fl.date_to ? `${fl.date_from ?? "start"} to ${fl.date_to ?? "today"}` : "All dates";
    const s = e.stats as Record<string, number>;
    const detail = e.kind === "dataset" ? `${s.clips ?? 0} clips · ${Math.round((s.seconds ?? 0) / 60)} min · ${s.skipped_redacted ?? 0} redacted lines excluded` : `${s.calls ?? 0} calls`;
    return `${period}${e.status === "succeeded" ? ` · ${detail}` : ""}`;
  };

  return (
    <>
      <div className="border-b px-4 py-2.5 sm:px-6"><FilterBar /></div>
      <div className="grid grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FileSpreadsheet className="size-4" />QA report (Excel)</CardTitle>
            <CardDescription>Summary, Agents, Criteria and per-call Details: failed items, both summaries and reviewer notes. Uses the filters above.</CardDescription>
          </CardHeader>
          <CardContent><Button onClick={() => run("excel")} disabled={!!busy}>{busy === "excel" ? <Loader2 className="animate-spin" /> : <Download />} Generate Excel</Button></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FileText className="size-4" />Call data (CSV)</CardTitle>
            <CardDescription>One row per call with every criterion answer, for BI tools or your own analysis.</CardDescription>
          </CardHeader>
          <CardContent><Button variant="outline" onClick={() => run("csv")} disabled={!!busy}>{busy === "csv" ? <Loader2 className="animate-spin" /> : <Download />} Generate CSV</Button></CardContent>
        </Card>
        {isAdmin && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><AudioLines className="size-4" />Speech dataset</CardTitle>
              <CardDescription>Analyst-corrected transcript lines as audio clips + text (Hugging Face audiofolder) for fine-tuning Whisper. Lines with personal data are excluded.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <label className="flex items-center gap-2 text-sm"><Switch checked={includeReviewed} onCheckedChange={setIncludeReviewed} /> Include unedited lines of reviewed calls</label>
              <div className="flex items-center gap-2"><Label className="whitespace-nowrap">Test split</Label><Input type="number" min={0} max={0.5} step={0.05} className="h-8 w-24" value={testFraction} onChange={(e) => setTestFraction(Number(e.target.value))} /></div>
              <Button variant="outline" onClick={() => run("dataset")} disabled={!!busy}>{busy === "dataset" ? <Loader2 className="animate-spin" /> : <Download />} Export dataset</Button>
            </CardContent>
          </Card>
        )}
        <Card className="lg:col-span-3">
          <CardHeader><CardTitle>Recent exports</CardTitle></CardHeader>
          <CardContent className="px-2">
            <Table>
              <THead><TR><TH>Created</TH><TH>Type</TH><TH>Contents</TH><TH>Status</TH><TH /></TR></THead>
              <TBody>
                {data?.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(e.created_at)}</TD>
                    <TD className="capitalize">{e.kind}</TD>
                    <TD className="text-muted-foreground">{describe(e)}{e.error && <div className="text-xs text-destructive">{e.error}</div>}</TD>
                    <TD><Badge variant={e.status === "succeeded" ? "success" : e.status === "failed" ? "destructive" : "default"}>{e.status}</Badge></TD>
                    <TD className="text-right">
                      {e.status === "succeeded" && <Button asChild size="sm" variant="ghost"><a href={`/api/exports/${e.id}/download`}><Download /> {e.filename}</a></Button>}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {data?.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">No exports yet.</p>}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

export default function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports & exports" description="Client QA reports, raw data, and training data for the speech model" />
      <Suspense><Exports /></Suspense>
    </>
  );
}

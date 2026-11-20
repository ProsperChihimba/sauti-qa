"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { useAuth } from "@/components/auth";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type ScorecardDef, type ScorecardRow } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

export default function ScorecardsPage() {
  const { isAdmin } = useAuth();
  const router = useRouter();
  const { data, mutate } = useSWR<ScorecardRow[]>("/scorecards");

  async function createNew() {
    const tpl = await api<ScorecardDef>("/scorecards/template");
    try {
      const sc = await api<ScorecardRow>("/scorecards", { method: "POST", json: { definition: { ...tpl, name: `${tpl.name} (copy ${new Date().toISOString().slice(0, 10)})` } } });
      router.push(`/scorecards/${sc.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function activate(id: number) {
    await api(`/scorecards/${id}/activate`, { method: "POST" });
    toast.success("Scorecard activated: new calls will be scored with it.");
    void mutate();
  }

  return (
    <>
      <PageHeader
        title="Scorecards"
        description="The QA criteria the AI scores against. Every save creates a new version; past evaluations keep the version they used."
        actions={isAdmin && <Button onClick={createNew}><Plus /> New scorecard</Button>}
      />
      <div className="p-4 sm:p-6">
        <Card>
          <Table>
            <THead><TR><TH>Name</TH><TH>Version</TH><TH className="text-right">Criteria</TH><TH className="text-right">Pass mark</TH><TH className="text-right">Calls scored</TH><TH>Saved</TH><TH /></TR></THead>
            <TBody>
              {data?.map((s) => (
                <TR key={s.id}>
                  <TD><Link className="font-medium hover:underline" href={`/scorecards/${s.id}`}>{s.name}</Link>{" "}{s.is_active && <Badge variant="success">Active</Badge>}</TD>
                  <TD className="tabular-nums">v{s.version}</TD>
                  <TD className="text-right tabular-nums">{s.definition.criteria.length}</TD>
                  <TD className="text-right tabular-nums">{s.pass_threshold}%</TD>
                  <TD className="text-right tabular-nums">{s.evaluations ?? 0}</TD>
                  <TD className="text-muted-foreground">{fmtDateTime(s.created_at)}</TD>
                  <TD className="text-right">{isAdmin && !s.is_active && <Button size="sm" variant="outline" onClick={() => activate(s.id)}>Activate</Button>}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      </div>
    </>
  );
}

"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Plus, Save, ShieldAlert, Trash2 } from "lucide-react";
import { useAuth } from "@/components/auth";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError, type Criterion, type ScorecardDef, type ScorecardRow } from "@/lib/api";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

function CriterionEditor({ c, onChange, onRemove, onMove, readOnly }: {
  c: Criterion; onChange: (c: Criterion) => void; onRemove: () => void; onMove: (d: -1 | 1) => void; readOnly: boolean;
}) {
  const set = <K extends keyof Criterion>(k: K, v: Criterion[K]) => onChange({ ...c, [k]: v });
  return (
    <div className="grid grid-cols-1 gap-3 rounded-lg border bg-card p-3 md:grid-cols-6">
      <div className="flex flex-col gap-1 md:col-span-2"><Label>Label</Label><Input value={c.label} disabled={readOnly} onChange={(e) => set("label", e.target.value)} /></div>
      <div className="flex flex-col gap-1"><Label>ID</Label><Input value={c.id} disabled={readOnly} className="font-mono text-xs" onChange={(e) => set("id", e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "_"))} /></div>
      <div className="flex flex-col gap-1"><Label>Section</Label><Input value={c.section} disabled={readOnly} onChange={(e) => set("section", e.target.value)} /></div>
      <div className="flex flex-col gap-1"><Label>Weight</Label><Input type="number" min={0.1} step={0.5} value={c.weight} disabled={readOnly} onChange={(e) => set("weight", Number(e.target.value))} /></div>
      <div className="flex items-end justify-end gap-1">
        {!readOnly && <>
          <Button size="icon" variant="ghost" onClick={() => onMove(-1)} aria-label="Move up"><ArrowUp /></Button>
          <Button size="icon" variant="ghost" onClick={() => onMove(1)} aria-label="Move down"><ArrowDown /></Button>
          <Button size="icon" variant="ghost" onClick={onRemove} aria-label="Remove criterion"><Trash2 /></Button>
        </>}
      </div>
      <div className="flex flex-col gap-1 md:col-span-6"><Label>Description (what the AI should check)</Label><Textarea rows={2} value={c.description} disabled={readOnly} onChange={(e) => set("description", e.target.value)} /></div>
      <div className="flex flex-col gap-1 md:col-span-3"><Label>Swahili example phrases when met (one per line)</Label><Textarea rows={3} defaultValue={c.examples.join("\n")} disabled={readOnly} onBlur={(e) => set("examples", lines(e.target.value))} /></div>
      <div className="flex flex-col gap-1 md:col-span-3"><Label>Example phrases when failed (one per line)</Label><Textarea rows={3} defaultValue={c.negative_examples.join("\n")} disabled={readOnly} onBlur={(e) => set("negative_examples", lines(e.target.value))} /></div>
      <div className="flex flex-wrap items-center gap-5 md:col-span-6">
        <label className="flex items-center gap-2 text-sm"><Switch checked={c.critical} disabled={readOnly} onCheckedChange={(v) => set("critical", v)} /> Critical (a &quot;no&quot; fails the whole call)</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={c.allow_na} disabled={readOnly} onCheckedChange={(v) => set("allow_na", v)} /> N/A allowed</label>
        {c.allow_na && <Input className="h-8 flex-1 text-xs" placeholder="When is N/A appropriate?" value={c.na_guidance ?? ""} disabled={readOnly} onChange={(e) => set("na_guidance", e.target.value)} />}
      </div>
    </div>
  );
}

export default function ScorecardPage() {
  const { id } = useParams<{ id: string }>();
  const { data } = useSWR<ScorecardRow>(`/scorecards/${id}`);
  return data ? <ScorecardEditor key={data.id} data={data} /> : null;
}

// Client-only stable row ids so reordering keeps each row's editor state.
type Row = Criterion & { _uid?: string };
let uidSeq = 0;
const uid = () => `c${++uidSeq}`;
const toJson = (d: ScorecardDef) => JSON.stringify(d, (k, v) => (k === "_uid" ? undefined : v), 2);

function normalise(d: ScorecardDef): ScorecardDef {
  return { ...d, criteria: d.criteria.map((c) => ({ ...c, _uid: (c as Row)._uid ?? uid(), negative_examples: c.negative_examples ?? [], examples: c.examples ?? [], description: c.description ?? "" })) };
}

function ScorecardEditor({ data }: { data: ScorecardRow }) {
  const id = data.id;
  const router = useRouter();
  const { isAdmin } = useAuth();
  const [def, setDef] = useState<ScorecardDef>(() => normalise(data.definition));
  const [json, setJson] = useState(() => toJson(data.definition));
  const [errors, setErrors] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const readOnly = !isAdmin;

  const totals = useMemo(() => {
    const sections = [...new Set(def.criteria.map((c) => c.section))];
    return { weight: def.criteria.reduce((s, c) => s + (Number(c.weight) || 0), 0), sections, critical: def.criteria.filter((c) => c.critical).length };
  }, [def]);

  const update = (d: ScorecardDef) => { setDef(d); setJson(toJson(d)); setErrors(null); };
  const setCrit = (i: number, c: Criterion) => update({ ...def, criteria: def.criteria.map((x, j) => (j === i ? c : x)) });
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= def.criteria.length) return;
    const arr = [...def.criteria];
    [arr[i], arr[j]] = [arr[j], arr[i]];
    update({ ...def, criteria: arr });
  };

  async function save() {
    let body = def;
    try {
      body = JSON.parse(json);
    } catch {
      setErrors("The JSON is not valid.");
      return;
    }
    setSaving(true);
    try {
      await api("/scorecards/validate", { method: "POST", json: { definition: body } });
      const saved = await api<ScorecardRow>(`/scorecards/${id}`, { method: "PUT", json: { definition: body } });
      toast.success(`Saved as version ${saved.version}${saved.is_active ? " (active)" : ""}`);
      router.replace(`/scorecards/${saved.id}`);
    } catch (e) {
      setErrors(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`${data.name} · v${data.version}`}
        description={data.is_active ? "Active: new calls are scored with this version." : "Not active."}
        actions={!readOnly && <Button onClick={save} disabled={saving}><Save /> Save as new version</Button>}
      />
      <div className="grid grid-cols-1 gap-4 p-4 sm:p-6">
        {errors && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{errors}</div>}
        <Card>
          <CardContent className="grid grid-cols-1 gap-3 pt-5 md:grid-cols-4">
            <div className="flex flex-col gap-1 md:col-span-2"><Label>Name</Label><Input value={def.name} disabled={readOnly} onChange={(e) => update({ ...def, name: e.target.value })} /></div>
            <div className="flex flex-col gap-1"><Label>Pass mark (%)</Label><Input type="number" min={0} max={100} value={def.pass_threshold} disabled={readOnly} onChange={(e) => update({ ...def, pass_threshold: Number(e.target.value) })} /></div>
            <div className="flex flex-wrap items-end gap-2 text-xs text-muted-foreground">
              {totals && <><Badge variant="secondary">{def.criteria.length} criteria</Badge><Badge variant="secondary">{totals.sections.length} sections</Badge><Badge variant="secondary">weight {totals.weight}</Badge><Badge variant="destructive"><ShieldAlert className="size-3" />{totals.critical} critical</Badge></>}
            </div>
            <div className="flex flex-col gap-1 md:col-span-4"><Label>Description</Label><Textarea rows={2} value={def.description ?? ""} disabled={readOnly} onChange={(e) => update({ ...def, description: e.target.value })} /></div>
            <div className="flex flex-col gap-1 md:col-span-4"><Label>Call reason categories (one per line; the AI prefers these labels)</Label>
              <Textarea rows={3} defaultValue={def.call_reasons.join("\n")} disabled={readOnly} onBlur={(e) => update({ ...def, call_reasons: lines(e.target.value) })} /></div>
          </CardContent>
        </Card>
        <Tabs defaultValue="form">
          <TabsList><TabsTrigger value="form">Criteria</TabsTrigger><TabsTrigger value="json">JSON</TabsTrigger></TabsList>
          <TabsContent value="form" className="flex flex-col gap-3">
            {def.criteria.map((c, i) => (
              <CriterionEditor key={(c as Row)._uid ?? i} c={c} readOnly={readOnly} onChange={(x) => setCrit(i, x)} onMove={(d) => move(i, d)}
                onRemove={() => update({ ...def, criteria: def.criteria.filter((_, j) => j !== i) })} />
            ))}
            {!readOnly && (
              <Button variant="outline" onClick={() => update({ ...def, criteria: [...def.criteria, { _uid: uid(), id: `criterion_${def.criteria.length + 1}`, section: def.criteria.at(-1)?.section ?? "General", label: "New criterion", description: "", examples: [], negative_examples: [], weight: 5, critical: false, allow_na: false }] })}>
                <Plus /> Add criterion
              </Button>
            )}
          </TabsContent>
          <TabsContent value="json">
            <Card>
              <CardHeader><CardTitle>Raw definition</CardTitle></CardHeader>
              <CardContent>
                <Textarea className="min-h-[32rem] font-mono text-xs" value={json} disabled={readOnly} spellCheck={false}
                  onChange={(e) => { setJson(e.target.value); try { setDef(normalise(JSON.parse(e.target.value))); setErrors(null); } catch { setErrors("The JSON is not valid yet."); } }} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

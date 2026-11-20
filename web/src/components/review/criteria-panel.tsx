"use client";

import { useState } from "react";
import { Bot, CircleSlash, Quote, ShieldAlert, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { api, type CallDetail, type EvalItem, type Evaluation } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

type Answer = EvalItem["answer"];
const LABEL: Record<Answer, string> = { yes: "Yes", no: "No", na: "N/A" };

function AnswerToggle({ value, ai, allowNa, onChange, disabled }: { value: Answer; ai: Answer; allowNa: boolean; onChange: (a: Answer) => void; disabled: boolean }) {
  const opts: Answer[] = allowNa ? ["yes", "no", "na"] : ["yes", "no"];
  return (
    <div className="inline-flex rounded-md border bg-card p-0.5" role="radiogroup">
      {opts.map((o) => (
        <button
          key={o}
          role="radio"
          aria-checked={value === o}
          disabled={disabled}
          onClick={() => value !== o && onChange(o)}
          title={o === ai ? "AI answer" : undefined}
          className={cn(
            "relative rounded px-2 py-0.5 text-xs font-medium transition-colors cursor-pointer disabled:cursor-not-allowed",
            value === o
              ? o === "yes" ? "bg-success text-white" : o === "no" ? "bg-destructive text-white" : "bg-muted-foreground text-white"
              : "text-muted-foreground hover:bg-muted",
          )}
        >
          {LABEL[o]}
          {o === ai && value !== o && <span className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-primary" />}
        </button>
      ))}
    </div>
  );
}

export function CriteriaPanel({ call, onEvaluation, onJump }: { call: CallDetail; onEvaluation: (e: Evaluation) => void; onJump: (idx: number) => void }) {
  const ev = call.evaluation!;
  const sc = call.scorecard;
  const [busy, setBusy] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const crit = new Map((sc?.criteria ?? []).map((c) => [c.id, c]));
  const sections: string[] = [];
  for (const it of ev.items) {
    const s = crit.get(it.criterion_id)?.section ?? "Other";
    if (!sections.includes(s)) sections.push(s);
  }

  async function override(it: EvalItem, answer: Answer) {
    setBusy(it.criterion_id);
    try {
      const updated = await api<Evaluation>(`/calls/${call.id}/evaluation/items/${it.criterion_id}`, {
        method: "PATCH", json: { answer, reason: reasons[it.criterion_id] || null },
      });
      onEvaluation(updated);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <div key={section}>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{section}</div>
          <div className="flex flex-col divide-y rounded-lg border bg-card">
            {ev.items.filter((it) => (crit.get(it.criterion_id)?.section ?? "Other") === section).map((it) => {
              const c = crit.get(it.criterion_id);
              const overridden = it.overridden_by_id != null;
              const lowConf = it.confidence < 0.6;
              return (
                <div key={it.criterion_id} className={cn("flex flex-col gap-1.5 p-3", it.answer === "no" && c?.critical && "bg-destructive/5")}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-sm font-medium">
                        {c?.critical && <ShieldAlert className="size-3.5 shrink-0 text-destructive" aria-label="Critical criterion" />}
                        <span>{c?.label ?? it.criterion_id}</span>
                        <span className="text-xs font-normal text-muted-foreground">({c?.weight ?? "?"})</span>
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                        {overridden ? (
                          <span className="inline-flex items-center gap-1 text-primary"><UserCheck className="size-3" />Overridden (AI said {LABEL[it.ai_answer]})</span>
                        ) : (
                          <span className="inline-flex items-center gap-1"><Bot className="size-3" />AI</span>
                        )}
                        <span className={cn("inline-flex items-center gap-1", lowConf && "font-medium text-[color-mix(in_oklch,var(--warning),black_30%)] dark:text-warning")}>
                          Confidence {Math.round(it.confidence * 100)}%
                        </span>
                        {it.repaired && <span className="inline-flex items-center gap-1"><CircleSlash className="size-3" />Repaired output</span>}
                      </div>
                    </div>
                    <AnswerToggle value={it.answer} ai={it.ai_answer} allowNa={!!c?.allow_na} disabled={busy === it.criterion_id} onChange={(a) => override(it, a)} />
                  </div>
                  {it.evidence_quote && (
                    <button
                      onClick={() => it.segment_idx != null && onJump(it.segment_idx)}
                      disabled={it.segment_idx == null}
                      className="flex items-start gap-1.5 rounded-md bg-muted/60 px-2 py-1.5 text-left text-xs italic hover:bg-accent disabled:cursor-default cursor-pointer"
                      title={it.segment_idx != null ? "Jump to this moment" : undefined}
                    >
                      <Quote className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
                      <span className="flex-1">{it.evidence_quote}</span>
                      {it.segment_idx != null && <span className="not-italic text-muted-foreground">#{it.segment_idx}</span>}
                    </button>
                  )}
                  {it.reasoning && <p className="text-xs text-muted-foreground">{it.reasoning}</p>}
                  {(overridden || busy === it.criterion_id) && (
                    <Input
                      className="h-7 text-xs"
                      placeholder="Reason for override (optional, saved with the next change)"
                      defaultValue={it.override_reason ?? ""}
                      onChange={(e) => setReasons({ ...reasons, [it.criterion_id]: e.target.value })}
                      onBlur={(e) => { if (overridden && e.target.value !== (it.override_reason ?? "")) void override(it, it.answer); }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

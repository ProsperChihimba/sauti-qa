"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, ArrowLeftRight, CheckCheck, Loader2, MessageSquarePlus, RefreshCw, Trash2,
} from "lucide-react";
import { useAuth } from "@/components/auth";
import { ReasonBadges, ReviewBadge, ScoreBadge, StatusBadge } from "@/components/badges";
import { AudioPlayer, type PlayerHandle } from "@/components/review/audio-player";
import { CriteriaPanel } from "@/components/review/criteria-panel";
import { Transcript } from "@/components/review/transcript";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type AuditEntry, type CallDetail, type Evaluation, type Note, type Segment } from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtScore, humanize } from "@/lib/format";

function Summary({ ev }: { ev: Evaluation }) {
  const [lang, setLang] = useState<"sw" | "en">("sw");
  const text = lang === "sw" ? ev.summary_sw : ev.summary_en;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">Summary</span>
        <div className="inline-flex rounded-md border p-0.5 text-[11px]">
          {(["sw", "en"] as const).map((l) => (
            <button key={l} onClick={() => setLang(l)} className={`rounded px-2 py-0.5 cursor-pointer ${lang === l ? "bg-muted font-medium" : "text-muted-foreground"}`}>
              {l === "sw" ? "Kiswahili" : "English"}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm leading-relaxed" lang={lang}>{text || "-"}</p>
      <div className="grid grid-cols-3 gap-2 pt-1 text-xs">
        <div><div className="text-muted-foreground">Reason</div><div className="font-medium">{ev.call_reason ?? "-"}</div></div>
        <div><div className="text-muted-foreground">Resolution</div><div className="font-medium">{humanize(ev.resolution_status)}</div></div>
        <div><div className="text-muted-foreground">Sentiment</div><div className="font-medium">{humanize(ev.sentiment)}</div></div>
      </div>
    </div>
  );
}

function Notes({ call, onChange }: { call: CallDetail; onChange: () => void }) {
  const { user, isAdmin } = useAuth();
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<"note" | "coaching">("coaching");
  async function add() {
    if (!body.trim()) return;
    try {
      await api<Note>(`/calls/${call.id}/notes`, { method: "POST", json: { body, kind } });
      setBody("");
      onChange();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <div className="flex flex-col gap-3">
      {call.notes.map((n) => (
        <div key={n.id} className="rounded-md border bg-card p-2.5">
          <div className="mb-1 flex items-center gap-2 text-[11px] text-muted-foreground">
            <Badge variant={n.kind === "coaching" ? "default" : "secondary"}>{n.kind === "coaching" ? "Coaching" : "Note"}</Badge>
            <span>{n.author_name ?? "Unknown"} · {fmtDateTime(n.created_at)}</span>
            {(n.author_id === user.id || isAdmin) && (
              <button className="ml-auto hover:text-destructive cursor-pointer" aria-label="Delete note"
                onClick={async () => { await api(`/calls/${call.id}/notes/${n.id}`, { method: "DELETE" }); onChange(); }}>
                <Trash2 className="size-3.5" />
              </button>
            )}
          </div>
          <p className="whitespace-pre-wrap text-sm">{n.body}</p>
        </div>
      ))}
      <div className="flex flex-col gap-2">
        <Textarea placeholder="Add a reviewer note or coaching point for the agent..." value={body} onChange={(e) => setBody(e.target.value)} rows={3} />
        <div className="flex items-center gap-2">
          <Select value={kind} onValueChange={(v) => setKind(v as "note" | "coaching")}>
            <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="coaching">Coaching</SelectItem><SelectItem value="note">Note</SelectItem></SelectContent>
          </Select>
          <Button size="sm" variant="outline" onClick={add} disabled={!body.trim()}><MessageSquarePlus /> Add</Button>
        </div>
      </div>
    </div>
  );
}

function History({ callId }: { callId: string }) {
  const { data } = useSWR<{ evaluations: Evaluation[]; audit: AuditEntry[] }>(`/calls/${callId}/history`);
  if (!data) return <Skeleton className="h-32" />;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">Evaluations</div>
        <ul className="divide-y rounded-md border">
          {data.evaluations.map((e) => (
            <li key={e.id} className="flex items-center gap-2 px-3 py-2">
              <span className="font-medium">Rev {e.rev}</span>
              <span className="text-xs text-muted-foreground">{humanize(e.trigger)} · {e.llm_provider}{e.llm_model ? ` / ${e.llm_model}` : ""} · {fmtDateTime(e.created_at)}</span>
              <span className="ml-auto"><ScoreBadge score={e.score} passed={e.passed} autoFail={e.auto_fail} /></span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">Activity</div>
        <ul className="flex flex-col gap-1.5">
          {data.audit.map((a) => (
            <li key={a.id} className="text-xs">
              <span className="text-muted-foreground">{fmtDateTime(a.at)}</span> · <span className="font-medium">{a.actor_name ?? (a.actor_api_key_id ? "API" : "System")}</span>{" "}
              {humanize(a.action.replace(".", " "))}
              {a.action === "evaluation.override" && a.after && <> : {String(a.after.criterion)} {String(a.before?.answer)} → {String(a.after.answer)}</>}
              {a.action === "transcript.edit" && a.after && <> : line {String(a.after.segment)}</>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function CallReview() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const sp = useSearchParams();
  const { user } = useAuth();
  const player = useRef<PlayerHandle>(null);
  const [time, setTime] = useState(0);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  const [follow, setFollow] = useState(true);
  const [completing, setCompleting] = useState(false);
  const [rescoring, setRescoring] = useState<number | null>(null);
  const [finalNote, setFinalNote] = useState("");

  const rescoringRef = useRef<number | null>(null);
  const { data: call, mutate } = useSWR<CallDetail>(`/calls/${id}`, {
    refreshInterval: (d) => (d && (!["done", "failed"].includes(d.status) || rescoringRef.current !== null) ? 2500 : 0),
    onSuccess: (d) => {
      // Rescore finished when a newer evaluation revision arrives.
      const from = rescoringRef.current;
      if (from === null) return;
      if (d.status === "done" && (d.evaluation?.rev ?? 0) > from) {
        rescoringRef.current = null;
        setRescoring(null);
        toast.success(`Re-scored: ${fmtScore(d.evaluation?.score)}`);
      } else if (d.status === "failed") {
        rescoringRef.current = null;
        setRescoring(null);
        toast.error(d.error ?? "Re-scoring failed");
      }
    },
  });

  // Auto-claim when arriving from "Start reviewing".
  const claimed = useRef(false);
  useEffect(() => {
    if (!call || claimed.current || sp.get("review") !== "1") return;
    claimed.current = true;
    if (call.review_status === "pending") void api(`/calls/${id}/review/claim`, { method: "POST" }).then(() => mutate());
  }, [call, id, mutate, sp]);


  const jump = useCallback((idx: number) => {
    const seg = call?.segments.find((s) => s.idx === idx);
    if (!seg) return;
    setFocusIdx(idx);
    player.current?.seek(seg.start_s);
    setTimeout(() => setFocusIdx(null), 2500);
  }, [call]);

  // Space toggles playback when not typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(t.tagName) && !t.isContentEditable) {
        e.preventDefault();
        player.current?.toggle();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!call) return <div className="grid grid-cols-1 gap-4 p-6"><Skeleton className="h-20" /><Skeleton className="h-96" /></div>;

  const ev = call.evaluation;
  const processing = !["done", "failed"].includes(call.status);

  function updateSegment(s: Segment) {
    void mutate({ ...call!, segments: call!.segments.map((x) => (x.id === s.id ? s : x)) }, { revalidate: false });
  }
  function updateEvaluation(e: Evaluation) {
    void mutate({ ...call!, evaluation: e, score: e.score, passed: e.passed, auto_fail: e.auto_fail }, { revalidate: true });
  }

  async function rescore() {
    try {
      await api(`/calls/${id}/rescore`, { method: "POST" });
      rescoringRef.current = ev?.rev ?? 0;
      setRescoring(ev?.rev ?? 0);
      toast.info("Re-scoring from the corrected transcript...");
      void mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function swap() {
    const segs = await api<Segment[]>(`/calls/${id}/speakers/swap`, { method: "POST" });
    void mutate({ ...call!, segments: segs }, { revalidate: false });
    toast.success("Agent and customer swapped. Re-score to update the evaluation.");
  }
  async function complete(next: boolean) {
    setCompleting(true);
    try {
      const r = await api<{ next_call_id: string | null }>(`/calls/${id}/review/complete`, { method: "POST", json: { note: finalNote || null, next } });
      setFinalNote("");
      toast.success("Marked as reviewed");
      if (next && r.next_call_id) router.push(`/calls/${r.next_call_id}?review=1`);
      else if (next) { toast.success("The review queue is empty."); router.push("/review"); }
      else void mutate();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setCompleting(false);
    }
  }

  const reviewable = call.status === "done" && call.review_status !== "reviewed";
  const otherReviewer = call.review_status === "in_review" && call.assigned_to_id !== null && call.assigned_to_id !== user.id;

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-card/95 px-4 py-3 backdrop-blur sm:px-6 max-lg:top-[41px]">
        <Button variant="ghost" size="icon" onClick={() => router.back()} aria-label="Back"><ArrowLeft /></Button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-base font-semibold">{call.agent?.name ?? "Unknown agent"}</h1>
            <StatusBadge status={call.status} />
            <ReviewBadge status={call.review_status} />
          </div>
          <div className="text-xs text-muted-foreground">
            {fmtDateTime(call.call_time)} · {call.queue ?? "No queue"} · {fmtDuration(call.duration_s)} · {call.external_id ?? call.original_filename}
          </div>
        </div>
        {ev && (
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className={`text-2xl font-semibold tabular-nums leading-none ${ev.auto_fail ? "text-destructive" : ev.passed ? "text-success" : ""}`}>{fmtScore(ev.score)}</div>
              <div className="text-[11px] text-muted-foreground">{ev.points_earned}/{ev.points_applicable} pts · pass {call.scorecard?.pass_threshold}%</div>
            </div>
            <ScoreBadge score={ev.score} passed={ev.passed} autoFail={ev.auto_fail} />
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {call.review_reasons.length > 0 && <ReasonBadges reasons={call.review_reasons} />}
          <Button variant="outline" size="sm" onClick={rescore} disabled={processing || rescoring !== null || !call.segments.length}>
            {rescoring !== null ? <Loader2 className="animate-spin" /> : <RefreshCw />} Re-score
          </Button>
          {reviewable && (
            <Button size="sm" onClick={() => complete(true)} disabled={completing || otherReviewer}>
              <CheckCheck /> Mark reviewed & next
            </Button>
          )}
        </div>
      </div>

      {otherReviewer && (
        <div className="flex items-center gap-2 border-b bg-warning/10 px-6 py-2 text-sm">
          <AlertTriangle className="size-4" /> Another analyst is reviewing this call.
        </div>
      )}
      {call.status === "failed" && (
        <div className="border-b bg-destructive/10 px-6 py-2 text-sm text-destructive">Processing failed: {call.error}</div>
      )}
      {processing && (
        <div className="flex items-center gap-2 border-b bg-accent px-6 py-2 text-sm"><Loader2 className="size-4 animate-spin" /> This call is being processed. The page will update automatically.</div>
      )}

      <div className="grid grid-cols-1 gap-4 p-4 sm:p-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        {/* Left: audio + transcript */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <CardContent className="pt-5">
              <AudioPlayer ref={player} src={call.has_audio ? `/api/calls/${id}/audio` : null} duration={call.duration_s} segments={call.segments} onTime={setTime} />
            </CardContent>
          </Card>
          <Card className="flex min-h-0 flex-col">
            <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
              <div>
                <CardTitle>Transcript</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  Machine transcript, personal data redacted. Double-click a line to correct it; click the speaker to relabel.
                  {call.speaker_method && <> Speakers: {call.speaker_method === "stereo" ? "stereo channels (exact)" : call.speaker_method === "llm" ? "AI-identified" : humanize(call.speaker_method)}.</>}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><Switch checked={follow} onCheckedChange={setFollow} /> Follow</label>
                <Button variant="ghost" size="sm" onClick={swap} disabled={!call.segments.length} title="Swap agent and customer"><ArrowLeftRight /> Swap</Button>
              </div>
            </CardHeader>
            <CardContent className="max-h-[calc(100vh-22rem)] min-h-64 overflow-y-auto px-3">
              <Transcript callId={id} segments={call.segments} currentTime={time} focusIdx={focusIdx} follow={follow}
                onSeek={(t) => player.current?.seek(t)} onChange={updateSegment} />
            </CardContent>
          </Card>
        </div>

        {/* Right: evaluation */}
        <div className="flex min-w-0 flex-col gap-4">
          {ev ? (
            <>
              <Card>
                <CardContent className="flex flex-col gap-3 pt-5">
                  <Summary ev={ev} />
                  {ev.flags.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      {ev.flags.map((f, i) => (
                        <button key={i} onClick={() => f.segment_idx != null && jump(f.segment_idx)}
                          className={`flex items-start gap-2 rounded-md px-2.5 py-2 text-left text-sm cursor-pointer ${f.type === "fraud" ? "bg-destructive/10 text-destructive" : "bg-warning/15"}`}>
                          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                          <span><span className="font-medium">{humanize(f.type)}:</span> {f.description}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
              <Tabs defaultValue="scorecard">
                <TabsList>
                  <TabsTrigger value="scorecard">Scorecard</TabsTrigger>
                  <TabsTrigger value="notes">Notes {call.notes.length > 0 && `(${call.notes.length})`}</TabsTrigger>
                  <TabsTrigger value="history">History</TabsTrigger>
                </TabsList>
                <TabsContent value="scorecard">
                  <p className="mb-2 text-xs text-muted-foreground">
                    {ev.scorecard_name} v{ev.scorecard_version} · scored by {ev.llm_provider}{ev.llm_model ? ` (${ev.llm_model})` : ""}. Change an answer to override it; the score updates instantly.
                  </p>
                  <CriteriaPanel call={call} onEvaluation={updateEvaluation} onJump={jump} />
                  {ev.repair_log.length > 0 && (
                    <details className="mt-3 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">AI output was repaired ({ev.repair_log.length})</summary>
                      <ul className="mt-1 list-disc pl-5">{ev.repair_log.map((r, i) => <li key={i}>{r}</li>)}</ul>
                    </details>
                  )}
                </TabsContent>
                <TabsContent value="notes"><Notes call={call} onChange={() => mutate()} /></TabsContent>
                <TabsContent value="history"><History callId={id} /></TabsContent>
              </Tabs>
              {reviewable && (
                <Card>
                  <CardContent className="flex flex-col gap-2 pt-5">
                    <Textarea rows={2} placeholder="Final review comment (optional)" value={finalNote} onChange={(e) => setFinalNote(e.target.value)} />
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button variant="outline" size="sm" onClick={() => complete(false)} disabled={completing || otherReviewer}>Mark reviewed</Button>
                      <Button size="sm" onClick={() => complete(true)} disabled={completing || otherReviewer}><CheckCheck /> Mark reviewed & next</Button>
                    </div>
                  </CardContent>
                </Card>
              )}
              {call.review_status === "reviewed" && (
                <p className="text-center text-xs text-muted-foreground">Reviewed {fmtDateTime(call.reviewed_at)}. <Link className="text-primary hover:underline" href="/review">Back to queue</Link></p>
              )}
            </>
          ) : (
            <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">{processing ? "Scoring will appear when processing finishes." : "This call has not been scored."}</CardContent></Card>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CallPage() {
  return <Suspense><CallReview /></Suspense>;
}

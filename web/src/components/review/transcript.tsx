"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { api, type Segment } from "@/lib/api";
import { fmtClock } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/input";

const SPEAKER_STYLE: Record<string, string> = {
  agent: "bg-[var(--chart-1)]/12 text-[color-mix(in_oklch,var(--chart-1),black_25%)] dark:text-[var(--chart-1)]",
  customer: "bg-[var(--chart-2)]/12 text-[color-mix(in_oklch,var(--chart-2),black_30%)] dark:text-[var(--chart-2)]",
  unknown: "bg-muted text-muted-foreground",
};
const NEXT_SPEAKER: Record<string, Segment["speaker"]> = { agent: "customer", customer: "agent", unknown: "agent" };

/** Render redaction tags as chips. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\[(?:PHONE|NIDA|CARD|ACCOUNT|NUMBER|PIN|EMAIL)\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[[A-Z]+\]$/.test(p) ? (
          <span key={i} className="mx-0.5 rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground" title="Redacted personal data">
            {p.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

interface Props {
  callId: string;
  segments: Segment[];
  currentTime: number;
  focusIdx: number | null;
  follow: boolean;
  onSeek: (t: number) => void;
  onChange: (s: Segment) => void;
}

export function Transcript({ callId, segments, currentTime, focusIdx, follow, onSeek, onChange }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const refs = useRef<Map<number, HTMLDivElement>>(new Map());
  const activeIdx = segments.findLast((s) => s.start_s <= currentTime + 0.05)?.idx ?? null;

  useEffect(() => {
    if (!follow || activeIdx == null || editing != null) return;
    refs.current.get(activeIdx)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIdx, follow, editing]);

  useEffect(() => {
    if (focusIdx == null) return;
    refs.current.get(focusIdx)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusIdx]);

  async function save(seg: Segment, changes: Partial<Pick<Segment, "text" | "speaker">>) {
    try {
      const updated = await api<Segment>(`/calls/${callId}/segments/${seg.id}`, { method: "PATCH", json: changes });
      onChange(updated);
      if (changes.text !== undefined && updated.text !== changes.text.trim()) toast.info("Personal data in your correction was redacted.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex flex-col">
      {segments.map((s) => {
        const active = s.idx === activeIdx;
        const focused = s.idx === focusIdx;
        const lowConf = s.confidence != null && s.confidence < 0.6;
        return (
          <div
            key={s.id}
            ref={(el) => { if (el) refs.current.set(s.idx, el); else refs.current.delete(s.idx); }}
            className={cn(
              "group grid grid-cols-[3.5rem_5.5rem_1fr] items-start gap-2 rounded-md px-2 py-1.5 transition-colors",
              active && "bg-accent",
              focused && "ring-2 ring-primary/60",
            )}
          >
            <button className="pt-0.5 text-left font-mono text-xs text-muted-foreground hover:text-primary cursor-pointer" onClick={() => onSeek(s.start_s)} title="Play from here">
              {fmtClock(s.start_s)}
            </button>
            <button
              className={cn("mt-px rounded px-1.5 py-0.5 text-[11px] font-medium capitalize cursor-pointer", SPEAKER_STYLE[s.speaker])}
              title="Click to change speaker"
              onClick={() => save(s, { speaker: NEXT_SPEAKER[s.speaker] })}
            >
              {s.speaker}
            </button>
            {editing === s.idx ? (
              <Textarea
                autoFocus
                value={draft}
                className="text-sm"
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => setEditing(null)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setEditing(null);
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (draft.trim() && draft.trim() !== s.text) void save(s, { text: draft });
                    setEditing(null);
                  }
                }}
              />
            ) : (
              <div className="flex items-start gap-1">
                <p
                  className={cn("flex-1 cursor-text text-sm leading-relaxed", lowConf && "decoration-warning underline decoration-dotted underline-offset-4")}
                  onDoubleClick={() => { setDraft(s.text); setEditing(s.idx); }}
                  title={lowConf ? `Low ASR confidence (${Math.round((s.confidence ?? 0) * 100)}%)` : undefined}
                >
                  <RichText text={s.text} />
                  {s.edited_at && <span className="ml-1.5 text-[10px] text-muted-foreground">(edited)</span>}
                </p>
                <button
                  className="invisible rounded p-1 text-muted-foreground hover:text-foreground group-hover:visible cursor-pointer"
                  onClick={() => { setDraft(s.text); setEditing(s.idx); }}
                  aria-label="Correct this line"
                >
                  <Pencil className="size-3.5" />
                </button>
              </div>
            )}
          </div>
        );
      })}
      {segments.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">No speech was detected in this recording.</p>}
    </div>
  );
}

import { AlertTriangle, CheckCircle2, CircleSlash, ShieldAlert, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fmtScore, humanize, REASON_LABELS } from "@/lib/format";
import type { Flag } from "@/lib/api";

export function ScoreBadge({ score, passed, autoFail }: { score: number | null; passed: boolean | null; autoFail?: boolean | null }) {
  if (autoFail) return <Badge variant="destructive"><ShieldAlert className="size-3" />Auto-fail</Badge>;
  if (score == null) return <span className="text-xs text-muted-foreground">-</span>;
  return <Badge variant={passed ? "success" : "warning"}>{fmtScore(score)}</Badge>;
}

const STATUS: Record<string, { label: string; variant: "secondary" | "default" | "success" | "destructive" | "warning" }> = {
  received: { label: "Queued", variant: "secondary" },
  preparing: { label: "Preparing audio", variant: "default" },
  transcribing: { label: "Transcribing", variant: "default" },
  labelling: { label: "Labelling speakers", variant: "default" },
  scoring: { label: "Scoring", variant: "default" },
  done: { label: "Done", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};
export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: humanize(status), variant: "secondary" as const };
  return <Badge variant={s.variant}>{s.label}</Badge>;
}

const REVIEW: Record<string, { label: string; variant: "secondary" | "default" | "success" | "warning" }> = {
  not_required: { label: "Auto-approved", variant: "secondary" },
  pending: { label: "Needs review", variant: "warning" },
  in_review: { label: "In review", variant: "default" },
  reviewed: { label: "Reviewed", variant: "success" },
};
export function ReviewBadge({ status }: { status: string }) {
  const s = REVIEW[status] ?? { label: humanize(status), variant: "secondary" as const };
  return <Badge variant={s.variant}>{s.label}</Badge>;
}

export function ReasonBadges({ reasons }: { reasons: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {reasons.map((r) => (
        <Badge key={r} variant={r === "auto_fail" || r === "flag:fraud" ? "destructive" : "outline"}>
          {REASON_LABELS[r] ?? humanize(r)}
        </Badge>
      ))}
    </div>
  );
}

export function FlagBadges({ flags }: { flags: Flag[] }) {
  const types = [...new Set(flags.map((f) => f.type))];
  return (
    <div className="flex flex-wrap gap-1">
      {types.map((t) => (
        <Badge key={t} variant={t === "fraud" ? "destructive" : "warning"}>
          <AlertTriangle className="size-3" />
          {humanize(t)}
        </Badge>
      ))}
    </div>
  );
}

export function AnswerBadge({ answer }: { answer: "yes" | "no" | "na" }) {
  if (answer === "yes") return <Badge variant="success"><CheckCircle2 className="size-3" />Yes</Badge>;
  if (answer === "no") return <Badge variant="destructive"><XCircle className="size-3" />No</Badge>;
  return <Badge variant="secondary"><CircleSlash className="size-3" />N/A</Badge>;
}

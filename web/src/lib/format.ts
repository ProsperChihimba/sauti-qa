export function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "-";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function fmtClock(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

const dtf = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Dar_es_Salaam",
});
export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dtf.format(new Date(iso)) : "-";
}

export function fmtScore(score: number | null | undefined): string {
  return score == null ? "-" : `${Math.round(score * 10) / 10}%`;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "-";
  const t = s.replace(/^flag:/, "").replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export const REASON_LABELS: Record<string, string> = {
  auto_fail: "Critical failure",
  low_score: "Low score",
  low_confidence: "Low AI confidence",
  unscorable: "Not scorable",
  repaired_output: "AI output repaired",
  no_speech: "No speech",
  "flag:fraud": "Fraud flag",
  "flag:wrong_information": "Wrong information",
  "flag:escalation_risk": "Escalation risk",
  "flag:other": "Flagged",
};

export function todayEAT(offsetDays = 0): string {
  const d = new Date(Date.now() + 3 * 3600 * 1000 + offsetDays * 86400 * 1000);
  return d.toISOString().slice(0, 10);
}

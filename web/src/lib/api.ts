// Typed client for the Sauti QA API (same origin: /api).

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? `${(d as { loc?: unknown[] }).loc?.slice(-1)[0] ?? ""}: ${(d as { msg: string }).msg}` : String(d)))
      .join("; ");
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : undefined;
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, messageFrom(detail, res.statusText || "Request failed"), detail);
  }
  return data as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

export function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// ---------- types ----------
export type Role = "admin" | "analyst";
export interface User { id: number; email: string; name: string; role: Role; is_active: boolean; last_login_at: string | null; created_at: string }
export interface Agent { id: number; name: string; team: string | null }
export interface Flag { type: string; description: string; segment_idx: number | null }

export interface CallListItem {
  id: string; external_id: string | null; source: string; original_filename: string | null; agent: Agent | null;
  queue: string | null; call_time: string; duration_s: number | null; status: string; review_status: string;
  review_reasons: string[]; error: string | null; created_at: string; score: number | null; passed: boolean | null;
  auto_fail: boolean | null; call_reason: string | null; sentiment: string | null; resolution_status: string | null;
  flags: Flag[];
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Segment {
  id: number; idx: number; start_s: number; end_s: number; speaker: "agent" | "customer" | "unknown";
  speaker_raw: string | null; text: string; asr_text: string; confidence: number | null; has_redaction: boolean;
  redactions: { type: string; start: number; end: number }[]; edited_at: string | null;
}
export interface EvalItem {
  criterion_id: string; position: number; answer: "yes" | "no" | "na"; ai_answer: "yes" | "no" | "na";
  evidence_quote: string | null; segment_idx: number | null; reasoning: string | null; confidence: number;
  repaired: boolean; overridden_by_id: number | null; override_reason: string | null; overridden_at: string | null;
}
export interface Evaluation {
  id: number; rev: number; scorecard_id: number; scorecard_name: string | null; scorecard_version: number | null;
  trigger: string; llm_provider: string; llm_model: string | null; score: number | null; points_earned: number;
  points_applicable: number; auto_fail: boolean; passed: boolean; call_reason: string | null;
  resolution_status: string | null; sentiment: string | null; summary_sw: string | null; summary_en: string | null;
  flags: Flag[]; repair_log: string[]; created_at: string; items: EvalItem[];
}
export interface Criterion {
  id: string; section: string; label: string; description: string; examples: string[]; negative_examples: string[];
  weight: number; critical: boolean; allow_na: boolean; na_guidance?: string | null; _uid?: string;
}
export interface ScorecardDef { name: string; description?: string; pass_threshold: number; call_reasons: string[]; criteria: Criterion[] }
export interface Note { id: number; kind: string; body: string; author_id: number | null; author_name: string | null; created_at: string }
export interface CallDetail extends CallListItem {
  channels: number | null; speech_s: number | null; asr_provider: string | null; asr_model: string | null;
  speaker_method: string | null; has_audio: boolean; assigned_to_id: number | null; reviewed_by_id: number | null;
  reviewed_at: string | null; meta: Record<string, unknown>; segments: Segment[]; evaluation: Evaluation | null;
  scorecard: (ScorecardDef & { id: number; key: string; version: number }) | null; notes: Note[];
}
export interface ScorecardRow {
  id: number; key: string; name: string; version: number; is_active: boolean; pass_threshold: number;
  created_at: string; created_by_id: number | null; definition: ScorecardDef; evaluations: number | null;
}
export interface Job {
  id: number; call_id: string | null; export_id: number | null; kind: string; queue: string; status: string;
  attempts: number; error: string | null; heartbeat_at: string | null; started_at: string | null;
  finished_at: string | null; created_at: string; updated_at: string;
}
export interface RuntimeSettings {
  review_score_threshold: number; review_confidence_threshold: number; review_on_flags: boolean;
  review_on_auto_fail: boolean; stereo_agent_channel: "left" | "right"; audio_retention_days: number;
}
export interface CriterionStat {
  criterion_id: string; label: string; section: string; critical: boolean; yes: number; no: number; na: number;
  overridden: number; pass_rate: number | null;
}
export interface Dashboard {
  kpis: {
    calls_total: number; calls_evaluated: number; minutes: number; avg_score: number | null; pass_rate: number | null;
    critical_breaches: number; pending_review: number; reviewed: number; flagged: number; failed_processing: number;
    processing: number; review_rate: number | null;
  };
  criteria: CriterionStat[];
  agents: { agent_id: number | null; agent: string; calls: number; avg_score: number | null; pass_rate: number | null; critical_breaches: number; minutes: number }[];
  call_reasons: { name: string; count: number }[];
  resolution: { name: string; count: number }[];
  sentiment: { name: string; count: number }[];
  trend: { date: string; calls: number; avg_score: number | null; pass_rate: number | null }[];
}
export interface AuditEntry {
  id: number; at: string; actor_user_id: number | null; actor_name: string | null; actor_api_key_id: number | null;
  action: string; entity: string; entity_id: string | null; before: Record<string, unknown> | null;
  after: Record<string, unknown> | null; ip: string | null;
}
export interface ExportRow {
  id: number; kind: string; status: string; filename: string | null; filters: Record<string, unknown>;
  stats: Record<string, unknown>; error: string | null; created_at: string;
}

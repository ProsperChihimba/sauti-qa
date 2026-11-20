"use client";

// Chart building blocks. Colours come from CSS tokens (validated categorical
// palette, light + dark); text always uses ink tokens, never series colours.
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const AXIS = { fontSize: 11, fill: "var(--muted-foreground)" };
const tooltipStyle = {
  contentStyle: {
    background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12,
    color: "var(--popover-foreground)", boxShadow: "0 4px 12px rgb(0 0 0 / 0.08)",
  },
  labelStyle: { color: "var(--muted-foreground)", marginBottom: 4 },
  itemStyle: { color: "var(--popover-foreground)", padding: 0 },
};

export function TrendChart({ data }: { data: { date: string; avg_score: number | null; pass_rate: number | null }[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--border)" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }}
          tickFormatter={(d: string) => d.slice(5)} minTickGap={24} />
        <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} unit="%" width={48} />
        <Tooltip {...tooltipStyle} cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
          formatter={(v) => (v == null ? "-" : `${v}%`)} />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: "var(--muted-foreground)" }} />
        <Line type="linear" dataKey="avg_score" name="Average score" stroke="var(--chart-1)" strokeWidth={2}
          dot={data.length < 20 ? { r: 4, strokeWidth: 2, stroke: "var(--card)" } : false} activeDot={{ r: 5 }} connectNulls />
        <Line type="linear" dataKey="pass_rate" name="Pass rate" stroke="var(--chart-2)" strokeWidth={2}
          dot={data.length < 20 ? { r: 4, strokeWidth: 2, stroke: "var(--card)" } : false} activeDot={{ r: 5 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Single-series horizontal bars with the value written at the bar end. */
export function HBars({ data, unit = "", max, height }: { data: { name: string; value: number }[]; unit?: string; max?: number; height?: number }) {
  const h = height ?? Math.max(120, data.length * 30 + 16);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 44, bottom: 0, left: 0 }} barCategoryGap={6}>
        <XAxis type="number" hide domain={[0, max ?? "dataMax"]} />
        <YAxis type="category" dataKey="name" tick={AXIS} tickLine={false} axisLine={false} width={150} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "var(--muted)" }} formatter={(v) => [`${v}${unit}`, ""]} separator="" />
        <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 4, 4, 0]} maxBarSize={18}
          label={{ position: "right", fontSize: 11, fill: "var(--foreground)", formatter: (v: unknown) => `${v}${unit}` }} />
      </BarChart>
    </ResponsiveContainer>
  );
}

const SENTIMENT_COLOR: Record<string, string> = {
  negative: "var(--div-neg)", mixed: "var(--div-mid)", neutral: "var(--div-mid)", positive: "var(--div-pos)",
};
const RESOLUTION_ORDER = ["resolved", "partially_resolved", "escalated", "unresolved", "unknown"];

/** 100% stacked single bar with a legend underneath (share of calls). */
export function ShareBar({ data, kind }: { data: { name: string; count: number }[]; kind: "sentiment" | "resolution" }) {
  const total = data.reduce((s, d) => s + d.count, 0) || 1;
  const order = kind === "sentiment" ? ["negative", "mixed", "neutral", "positive"] : RESOLUTION_ORDER;
  const sorted = [...data].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  const color = (name: string, i: number) =>
    kind === "sentiment" ? SENTIMENT_COLOR[name] ?? "var(--div-mid)" : `var(--chart-${(RESOLUTION_ORDER.indexOf(name) >= 0 ? RESOLUTION_ORDER.indexOf(name) : i) + 1})`;
  const label = (n: string) => n.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  if (!data.length) return <p className="text-sm text-muted-foreground">No data</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full">
        {sorted.map((d, i) => (
          <div key={d.name} title={`${label(d.name)}: ${d.count} (${Math.round((d.count / total) * 100)}%)`}
            style={{ width: `${(d.count / total) * 100}%`, background: color(d.name, i) }}
            className={kind === "sentiment" && d.name === "mixed" ? "bg-[repeating-linear-gradient(45deg,transparent_0_3px,rgb(0_0_0/0.15)_3px_5px)]" : ""} />
        ))}
      </div>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {sorted.map((d, i) => (
          <li key={d.name} className="flex items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: color(d.name, i) }} />
            <span className="flex-1 truncate text-muted-foreground">{label(d.name)}</span>
            <span className="tabular-nums font-medium">{Math.round((d.count / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export { Cell };

"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { PageHeader } from "@/components/app-shell";
import { CallTable } from "@/components/call-table";
import { FilterBar, useFilters, useSetParams } from "@/components/filters";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { qs, type CallListItem, type Page } from "@/lib/api";

const ALL = "__all";

function Calls() {
  const f = useFilters();
  const sp = useSearchParams();
  const set = useSetParams();
  const page = Number(sp.get("page") ?? 1);
  const sort = sp.get("sort") ?? "call_time";
  const { data } = useSWR<Page<CallListItem>>(`/calls${qs({ ...f, page, page_size: 25, sort, order: sp.get("order") ?? "desc" })}`, {
    refreshInterval: (d) => (d?.items.some((c) => !["done", "failed"].includes(c.status)) ? 4000 : 30000),
  });

  const extra = (
    <>
      <Select value={f.review_status ?? ALL} onValueChange={(v) => set({ review_status: v })}>
        <SelectTrigger className="h-8 w-36 text-xs" aria-label="Review status"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Any review state</SelectItem>
          <SelectItem value="pending">Needs review</SelectItem>
          <SelectItem value="in_review">In review</SelectItem>
          <SelectItem value="reviewed">Reviewed</SelectItem>
          <SelectItem value="not_required">Auto-approved</SelectItem>
        </SelectContent>
      </Select>
      <Select value={f.passed ?? (f.auto_fail === "true" ? "af" : ALL)} onValueChange={(v) => set(v === "af" ? { auto_fail: "true", passed: null } : { passed: v, auto_fail: null })}>
        <SelectTrigger className="h-8 w-32 text-xs" aria-label="Result"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Any result</SelectItem>
          <SelectItem value="true">Passed</SelectItem>
          <SelectItem value="false">Failed</SelectItem>
          <SelectItem value="af">Critical failure</SelectItem>
        </SelectContent>
      </Select>
      <Select value={sort} onValueChange={(v) => set({ sort: v, order: v === "score" ? "asc" : "desc" })}>
        <SelectTrigger className="h-8 w-36 text-xs" aria-label="Sort"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="call_time">Newest first</SelectItem>
          <SelectItem value="score">Lowest score first</SelectItem>
          <SelectItem value="duration_s">Longest first</SelectItem>
        </SelectContent>
      </Select>
    </>
  );

  return (
    <>
      <div className="border-b px-4 py-2.5 sm:px-6"><FilterBar search extra={extra} /></div>
      <div className="p-4 sm:p-6">
        <Card>{data ? <CallTable page={data} onPage={(p) => set({ page: String(p) })} /> : <Skeleton className="m-4 h-64" />}</Card>
      </div>
    </>
  );
}

export default function CallsPage() {
  return (
    <>
      <PageHeader title="Calls" description="Every call received, with its AI score and review state" />
      <Suspense><Calls /></Suspense>
    </>
  );
}

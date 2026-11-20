"use client";

import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { CallListItem, Page } from "@/lib/api";
import { fmtDateTime, fmtDuration } from "@/lib/format";
import { FlagBadges, ReasonBadges, ReviewBadge, ScoreBadge, StatusBadge } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export function CallTable({ page, showReasons = false, onPage }: { page: Page<CallListItem>; showReasons?: boolean; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(page.total / page.page_size));
  return (
    <div>
      <Table>
        <THead>
          <TR>
            <TH>Call time</TH><TH>Agent</TH><TH>Queue</TH><TH className="text-right">Duration</TH><TH>Score</TH>
            <TH>Reason for call</TH><TH>{showReasons ? "Why review" : "Review"}</TH><TH>Status</TH>
          </TR>
        </THead>
        <TBody>
          {page.items.map((c) => (
            <TR key={c.id} className="cursor-pointer">
              <TD className="whitespace-nowrap">
                <Link href={`/calls/${c.id}`} className="font-medium hover:underline">{fmtDateTime(c.call_time)}</Link>
                <div className="max-w-48 truncate text-xs text-muted-foreground">{c.external_id ?? c.original_filename}</div>
              </TD>
              <TD>{c.agent?.name ?? <span className="text-muted-foreground">-</span>}</TD>
              <TD className="text-muted-foreground">{c.queue ?? "-"}</TD>
              <TD className="text-right tabular-nums">{fmtDuration(c.duration_s)}</TD>
              <TD><ScoreBadge score={c.score} passed={c.passed} autoFail={c.auto_fail} /></TD>
              <TD className="max-w-48">
                <div className="truncate">{c.call_reason ?? "-"}</div>
                {c.flags.length > 0 && <div className="mt-1"><FlagBadges flags={c.flags} /></div>}
              </TD>
              <TD>{showReasons ? <ReasonBadges reasons={c.review_reasons} /> : <ReviewBadge status={c.review_status} />}</TD>
              <TD><StatusBadge status={c.status} /></TD>
            </TR>
          ))}
        </TBody>
      </Table>
      {page.items.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">No calls match these filters.</p>}
      <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
        <span>{page.total.toLocaleString()} calls</span>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
          <span>Page {page.page} of {pages}</span>
          <Button variant="ghost" size="icon" disabled={page.page >= pages} onClick={() => onPage(page.page + 1)} aria-label="Next page"><ChevronRight /></Button>
        </div>
      </div>
    </div>
  );
}

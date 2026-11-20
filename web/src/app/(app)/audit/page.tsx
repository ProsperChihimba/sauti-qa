"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { AdminOnly } from "@/components/admin-only";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { qs, type AuditEntry, type Page } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

function Diff({ e }: { e: AuditEntry }) {
  const parts: string[] = [];
  if (e.before) parts.push(`before: ${JSON.stringify(e.before)}`);
  if (e.after) parts.push(`after: ${JSON.stringify(e.after)}`);
  return <span className="line-clamp-2 font-mono text-[11px] text-muted-foreground" title={parts.join("\n")}>{parts.join("  ")}</span>;
}

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const { data } = useSWR<Page<AuditEntry>>(`/audit${qs({ action, page, page_size: 50 })}`);
  return (
    <>
      <PageHeader title="Audit log" description="Every override, transcript edit, review, export and admin change" />
      <AdminOnly>
        <div className="flex flex-col gap-3 p-4 sm:p-6">
          <Input className="h-8 w-72 text-xs" placeholder="Filter by action, e.g. evaluation.override" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />
          <Card>
            <Table>
              <THead><TR><TH>When</TH><TH>Who</TH><TH>Action</TH><TH>Target</TH><TH>Details</TH><TH>IP</TH></TR></THead>
              <TBody>
                {data?.items.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(e.at)}</TD>
                    <TD>{e.actor_name ?? (e.actor_api_key_id ? `API key #${e.actor_api_key_id}` : "System")}</TD>
                    <TD className="font-mono text-xs">{e.action}</TD>
                    <TD className="text-xs">{e.entity === "call" && e.entity_id ? <Link className="hover:underline" href={`/calls/${e.entity_id}`}>call {e.entity_id.slice(0, 8)}</Link> : `${e.entity} ${e.entity_id ?? ""}`}</TD>
                    <TD className="max-w-md"><Diff e={e} /></TD>
                    <TD className="text-xs text-muted-foreground">{e.ip ?? "-"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="flex items-center justify-end gap-2 border-t p-2 text-xs text-muted-foreground">
              {data && <span>{data.total} entries</span>}
              <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button size="sm" variant="ghost" disabled={!data || page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </Card>
        </div>
      </AdminOnly>
    </>
  );
}

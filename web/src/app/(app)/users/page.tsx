"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Copy, KeyRound, Plus } from "lucide-react";
import { AdminOnly } from "@/components/admin-only";
import { useAuth } from "@/components/auth";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type User } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface ApiKey { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; revoked_at: string | null }

function NewUser({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "analyst", password: "" });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/users", { method: "POST", json: form });
      toast.success(`${form.name} can now sign in`);
      setOpen(false);
      setForm({ name: "", email: "", role: "analyst", password: "" });
      onDone();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><Plus /> Add user</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Add user</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1"><Label>Full name</Label><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Email</Label><Input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Role</Label>
            <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="analyst">Analyst - reviews calls</SelectItem><SelectItem value="admin">Admin - manages everything</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1"><Label>Initial password (min. 10 characters)</Label><Input required minLength={10} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <DialogFooter><Button type="submit">Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ApiKeys() {
  const { data, mutate } = useSWR<ApiKey[]>("/api-keys");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  async function create() {
    const k = await api<ApiKey & { key: string }>("/api-keys", { method: "POST", json: { name } });
    setCreated(k.key);
    setName("");
    void mutate();
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />API keys</CardTitle>
        <CardDescription>For the call recorder to push recordings to <code className="font-mono">POST /api/v1/calls</code> with the <code className="font-mono">X-API-Key</code> header.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex gap-2">
          <Input placeholder="Key name, e.g. Recorder Dar 1" value={name} onChange={(e) => setName(e.target.value)} />
          <Button variant="outline" disabled={!name.trim()} onClick={create}>Create key</Button>
        </div>
        {created && (
          <div className="rounded-md border border-primary/40 bg-accent p-3 text-sm">
            <div className="mb-1 font-medium">Copy this key now. It will not be shown again.</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all font-mono text-xs">{created}</code>
              <Button size="sm" variant="outline" onClick={() => { void navigator.clipboard.writeText(created); toast.success("Copied"); }}><Copy /> Copy</Button>
            </div>
          </div>
        )}
        <Table>
          <THead><TR><TH>Name</TH><TH>Prefix</TH><TH>Created</TH><TH>Last used</TH><TH /></TR></THead>
          <TBody>
            {data?.map((k) => (
              <TR key={k.id}>
                <TD className="font-medium">{k.name}</TD>
                <TD className="font-mono text-xs">sqa_{k.prefix}_...</TD>
                <TD className="text-muted-foreground">{fmtDateTime(k.created_at)}</TD>
                <TD className="text-muted-foreground">{fmtDateTime(k.last_used_at)}</TD>
                <TD className="text-right">
                  {k.revoked_at ? <Badge variant="secondary">Revoked</Badge> : (
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={async () => { if (confirm(`Revoke "${k.name}"? Integrations using it will stop working.`)) { await api(`/api-keys/${k.id}`, { method: "DELETE" }); void mutate(); } }}>Revoke</Button>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function Users() {
  const { user: me } = useAuth();
  const { data, mutate } = useSWR<User[]>("/users");
  async function patch(u: User, body: Partial<User>) {
    try {
      await api(`/users/${u.id}`, { method: "PATCH", json: body });
      void mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function reset(u: User) {
    const pw = prompt(`New password for ${u.name} (min. 10 characters):`);
    if (!pw) return;
    try {
      await api(`/users/${u.id}/reset-password`, { method: "POST", json: { new_password: pw } });
      toast.success("Password reset; existing sessions were signed out.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div><CardTitle>Users</CardTitle><CardDescription>Analysts review calls. Admins also manage scorecards, users, settings and exports.</CardDescription></div>
        <NewUser onDone={() => mutate()} />
      </CardHeader>
      <CardContent>
        <Table>
          <THead><TR><TH>Name</TH><TH>Email</TH><TH>Role</TH><TH>Last sign-in</TH><TH>Status</TH><TH /></TR></THead>
          <TBody>
            {data?.map((u) => (
              <TR key={u.id}>
                <TD className="font-medium">{u.name}</TD>
                <TD className="text-muted-foreground">{u.email}</TD>
                <TD>
                  <Select value={u.role} disabled={u.id === me.id} onValueChange={(v) => patch(u, { role: v as User["role"] })}>
                    <SelectTrigger className="h-8 w-28 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="analyst">Analyst</SelectItem><SelectItem value="admin">Admin</SelectItem></SelectContent>
                  </Select>
                </TD>
                <TD className="text-muted-foreground">{fmtDateTime(u.last_login_at)}</TD>
                <TD>{u.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="secondary">Disabled</Badge>}</TD>
                <TD className="text-right whitespace-nowrap">
                  <Button size="sm" variant="ghost" onClick={() => reset(u)}>Reset password</Button>
                  {u.id !== me.id && <Button size="sm" variant="ghost" onClick={() => patch(u, { is_active: !u.is_active })}>{u.is_active ? "Disable" : "Enable"}</Button>}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export default function UsersPage() {
  return (
    <>
      <PageHeader title="Users & API keys" description="Who can sign in, and which integrations can push calls" />
      <AdminOnly><div className="grid grid-cols-1 gap-4 p-4 sm:p-6"><Users /><ApiKeys /></div></AdminOnly>
    </>
  );
}

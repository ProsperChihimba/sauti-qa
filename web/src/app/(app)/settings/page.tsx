"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { AdminOnly } from "@/components/admin-only";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, type RuntimeSettings } from "@/lib/api";

export default function SettingsPage() {
  const { data } = useSWR<RuntimeSettings>("/settings");
  return data ? <SettingsForm initial={data} /> : null;
}

function SettingsForm({ initial }: { initial: RuntimeSettings }) {
  const { mutate } = useSWR<RuntimeSettings>("/settings");
  const [s, setS] = useState<RuntimeSettings>(initial);

  async function save() {
    try {
      const r = await api<RuntimeSettings>("/settings", { method: "PUT", json: s });
      void mutate(r, { revalidate: false });
      toast.success("Settings saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader title="Settings" description="Applied to new calls immediately. Infrastructure settings (models, storage) live in the .env file." actions={<Button onClick={save}>Save</Button>} />
      <AdminOnly>
        <div className="grid grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Review routing</CardTitle><CardDescription>Which calls are sent to analysts. All other calls are auto-approved.</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <label className="flex items-center justify-between gap-3 text-sm">Send critical failures (auto-fail) to review<Switch checked={s.review_on_auto_fail} onCheckedChange={(v) => setS({ ...s, review_on_auto_fail: v })} /></label>
              <label className="flex items-center justify-between gap-3 text-sm">Send flagged calls (fraud, wrong information, escalation risk)<Switch checked={s.review_on_flags} onCheckedChange={(v) => setS({ ...s, review_on_flags: v })} /></label>
              <div className="flex flex-col gap-1"><Label>Send calls scoring below (%)</Label><Input type="number" min={0} max={100} value={s.review_score_threshold} onChange={(e) => setS({ ...s, review_score_threshold: Number(e.target.value) })} /></div>
              <div className="flex flex-col gap-1"><Label>Send calls where any AI answer has confidence below (0-1)</Label><Input type="number" min={0} max={1} step={0.05} value={s.review_confidence_threshold} onChange={(e) => setS({ ...s, review_confidence_threshold: Number(e.target.value) })} /></div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Audio</CardTitle><CardDescription>Recording format and data retention.</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1"><Label>Agent channel in stereo recordings</Label>
                <Select value={s.stereo_agent_channel} onValueChange={(v) => setS({ ...s, stereo_agent_channel: v as "left" | "right" })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="left">Left channel</SelectItem><SelectItem value="right">Right channel</SelectItem></SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">Can be overridden per call with agent_channel in the sidecar or API metadata.</p>
              </div>
              <div className="flex flex-col gap-1"><Label>Delete audio after (days, 0 = keep forever)</Label><Input type="number" min={0} value={s.audio_retention_days} onChange={(e) => setS({ ...s, audio_retention_days: Number(e.target.value) })} />
                <p className="text-xs text-muted-foreground">Redacted transcripts and scores are kept for reporting. Deletion runs hourly.</p></div>
            </CardContent>
          </Card>
        </div>
      </AdminOnly>
    </>
  );
}

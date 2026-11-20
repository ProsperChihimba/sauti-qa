"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { CheckCircle2, FileAudio, UploadCloud, XCircle } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";

interface Result { accepted: { id: string; filename: string; created: boolean; duplicate_of: string | null }[]; rejected: { filename: string; error: string }[] }

const BATCH = 10;

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [agent, setAgent] = useState("");
  const [queue, setQueue] = useState("");
  const [callTime, setCallTime] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [results, setResults] = useState<Result>({ accepted: [], rejected: [] });
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function add(list: FileList | null) {
    if (!list) return;
    setFiles((prev) => [...prev, ...Array.from(list).filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  }

  async function upload() {
    const all: Result = { accepted: [], rejected: [] };
    // Sidecars travel in the same batch as their audio file.
    const audio = files.filter((f) => !f.name.toLowerCase().endsWith(".json"));
    const sidecars = new Map(files.filter((f) => f.name.toLowerCase().endsWith(".json")).map((f) => [f.name.replace(/\.json$/i, ""), f]));
    setProgress(0);
    for (let i = 0; i < audio.length; i += BATCH) {
      const fd = new FormData();
      for (const f of audio.slice(i, i + BATCH)) {
        fd.append("files", f);
        const sc = sidecars.get(f.name.replace(/\.[^.]+$/, ""));
        if (sc) fd.append("files", sc);
      }
      if (agent) fd.append("agent_name", agent);
      if (queue) fd.append("queue", queue);
      if (callTime) fd.append("call_time", callTime);
      try {
        const res = await fetch("/api/calls/upload", { method: "POST", body: fd, credentials: "same-origin" });
        const body = await res.json();
        if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : "Upload failed");
        all.accepted.push(...body.accepted);
        all.rejected.push(...body.rejected);
      } catch (e) {
        audio.slice(i, i + BATCH).forEach((f) => all.rejected.push({ filename: f.name, error: (e as Error).message }));
      }
      setProgress(Math.min(audio.length, i + BATCH) / audio.length);
    }
    setResults(all);
    setFiles([]);
    setProgress(null);
    toast.success(`${all.accepted.length} uploaded, ${all.rejected.length} rejected`);
  }

  return (
    <>
      <PageHeader title="Upload calls" description="Bulk upload recordings from your computer. Recorders can also push via the API or the SFTP inbox." />
      <div className="grid grid-cols-1 gap-4 p-4 sm:p-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardContent className="pt-5">
            <div
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
              onClick={() => input.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-10 text-center transition-colors ${drag ? "border-primary bg-accent" : "hover:bg-muted/50"}`}
            >
              <UploadCloud className="size-8 text-muted-foreground" />
              <div className="text-sm font-medium">Drop recordings here or click to choose</div>
              <div className="text-xs text-muted-foreground">WAV, MP3, OGG, OPUS, FLAC, M4A, AMR, GSM. Optional .json sidecar per file (same name).</div>
              <input ref={input} type="file" multiple hidden accept="audio/*,.amr,.gsm,.json" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
            </div>
            {files.length > 0 && (
              <ul className="mt-4 max-h-64 divide-y overflow-y-auto rounded-md border text-sm">
                {files.map((f) => (
                  <li key={f.name + f.size} className="flex items-center gap-2 px-3 py-1.5">
                    <FileAudio className="size-4 text-muted-foreground" />
                    <span className="flex-1 truncate">{f.name}</span>
                    <span className="text-xs text-muted-foreground">{(f.size / 1024 / 1024).toFixed(1)} MB</span>
                    <button className="text-muted-foreground hover:text-destructive cursor-pointer" onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={`Remove ${f.name}`}>
                      <XCircle className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Call details</CardTitle>
            <CardDescription>Applied to every file in this upload (a sidecar file overrides them).</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5"><Label htmlFor="agent">Agent name</Label><Input id="agent" value={agent} onChange={(e) => setAgent(e.target.value)} placeholder="e.g. Neema Mushi" /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor="queue">Queue</Label><Input id="queue" value={queue} onChange={(e) => setQueue(e.target.value)} placeholder="e.g. Prepaid, M-Pesa" /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor="ct">Call time (EAT)</Label><Input id="ct" type="datetime-local" value={callTime} onChange={(e) => setCallTime(e.target.value)} /></div>
            <Button disabled={!files.some((f) => !f.name.endsWith(".json")) || progress !== null} onClick={upload}>
              {progress !== null ? `Uploading ${Math.round(progress * 100)}%` : `Upload ${files.filter((f) => !f.name.endsWith(".json")).length || ""} files`}
            </Button>
          </CardContent>
        </Card>
        {(results.accepted.length > 0 || results.rejected.length > 0) && (
          <Card className="xl:col-span-3">
            <CardHeader><CardTitle>Upload results</CardTitle></CardHeader>
            <CardContent>
              <ul className="divide-y text-sm">
                {results.accepted.map((a) => (
                  <li key={a.id + a.filename} className="flex items-center gap-2 py-1.5">
                    <CheckCircle2 className="size-4 text-success" />
                    <span className="flex-1 truncate">{a.filename}</span>
                    <span className="text-xs text-muted-foreground">{a.created ? "Processing" : "Already uploaded"}</span>
                    <Link href={`/calls/${a.id}`} className="text-xs text-primary hover:underline">Open</Link>
                  </li>
                ))}
                {results.rejected.map((r) => (
                  <li key={r.filename} className="flex items-center gap-2 py-1.5">
                    <XCircle className="size-4 text-destructive" />
                    <span className="flex-1 truncate">{r.filename}</span>
                    <span className="text-xs text-destructive">{r.error}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}

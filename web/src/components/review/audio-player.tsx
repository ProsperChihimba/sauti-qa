"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Pause, Play, RotateCcw, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtClock } from "@/lib/format";

export interface PlayerHandle {
  seek: (t: number, play?: boolean) => void;
  toggle: () => void;
}

interface Props {
  src: string | null;
  duration: number | null;
  segments: { start_s: number; end_s: number; speaker: string }[];
  onTime: (t: number) => void;
}

/** Audio player with a speaker-coloured timeline (agent above, customer below). */
export const AudioPlayer = forwardRef<PlayerHandle, Props>(function AudioPlayer({ src, duration, segments, onTime }, ref) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(duration ?? 0);
  const [rate, setRate] = useState(1);

  useImperativeHandle(ref, () => ({
    seek(t, play = true) {
      const a = audio.current;
      if (!a) return;
      a.currentTime = Math.max(0, t);
      setTime(a.currentTime);
      onTime(a.currentTime);
      if (play) void a.play();
    },
    toggle() {
      const a = audio.current;
      if (!a) return;
      if (a.paused) void a.play();
      else a.pause();
    },
  }));

  useEffect(() => {
    if (audio.current) audio.current.playbackRate = rate;
  }, [rate]);

  if (!src)
    return <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">Audio was deleted under the retention policy. The transcript and scores are kept.</div>;

  const total = dur || duration || 1;
  const pct = (t: number) => `${(t / total) * 100}%`;
  return (
    <div className="flex flex-col gap-2">
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
        onTimeUpdate={(e) => { setTime(e.currentTarget.currentTime); onTime(e.currentTarget.currentTime); }}
      />
      <div
        className="relative h-10 cursor-pointer rounded-md bg-muted"
        role="slider"
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(time)}
        tabIndex={0}
        onKeyDown={(e) => {
          if (!audio.current) return;
          if (e.key === "ArrowRight") audio.current.currentTime += 5;
          if (e.key === "ArrowLeft") audio.current.currentTime -= 5;
        }}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const t = ((e.clientX - r.left) / r.width) * total;
          if (audio.current) audio.current.currentTime = t;
        }}
      >
        {segments.map((s, i) => (
          <div
            key={i}
            className={`absolute h-3 rounded-[2px] ${s.speaker === "agent" ? "top-2 bg-[var(--chart-1)]" : s.speaker === "customer" ? "bottom-2 bg-[var(--chart-2)]" : "top-3.5 bg-muted-foreground/50"}`}
            style={{ left: pct(s.start_s), width: `max(2px, ${pct(s.end_s - s.start_s)})` }}
          />
        ))}
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-foreground" style={{ left: pct(time) }} />
      </div>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="ghost" aria-label="Back 5 seconds" onClick={() => audio.current && (audio.current.currentTime -= 5)}><RotateCcw /></Button>
        <Button size="icon" aria-label={playing ? "Pause" : "Play"} onClick={() => (audio.current?.paused ? audio.current.play() : audio.current?.pause())}>
          {playing ? <Pause /> : <Play />}
        </Button>
        <Button size="icon" variant="ghost" aria-label="Forward 5 seconds" onClick={() => audio.current && (audio.current.currentTime += 5)}><RotateCw /></Button>
        <span className="ml-2 text-xs tabular-nums text-muted-foreground">{fmtClock(time)} / {fmtClock(total)}</span>
        <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span className="hidden items-center gap-1 sm:flex"><span className="size-2 rounded-sm bg-[var(--chart-1)]" />Agent</span>
          <span className="hidden items-center gap-1 sm:flex"><span className="size-2 rounded-sm bg-[var(--chart-2)]" />Customer</span>
          <select className="rounded border bg-card px-1 py-0.5 text-xs" value={rate} onChange={(e) => setRate(Number(e.target.value))} aria-label="Playback speed">
            {[0.75, 1, 1.25, 1.5, 2].map((r) => <option key={r} value={r}>{r}x</option>)}
          </select>
        </div>
      </div>
    </div>
  );
});

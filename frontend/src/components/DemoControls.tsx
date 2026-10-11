"use client";
import type { CaseEvents, Speed } from "@/lib/useCaseEvents";
import { Icon } from "./Icon";

interface Props {
  events: CaseEvents;
  speed: Speed;
  onSpeed: (s: Speed) => void;
}

// Playback controls sit in the page toolbar (always visible, never over content).
export function DemoControls({ events, speed, onSpeed }: Props) {
  const btn = "press inline-flex min-h-11 items-center gap-1.5 rounded-none border border-line bg-surface px-3 hover:border-ink lg:min-h-9";
  const ended = events.status === "ended";
  return (
    <div className="relative flex flex-wrap items-center gap-2">
      {events.controllable && (
        <>
          <button className={btn} onClick={events.status === "paused" ? events.play : events.pause} disabled={ended}>
            <Icon name={events.status === "paused" ? "play" : "pause"} size={14} />
            {events.status === "paused" ? "Play" : "Pause"}
          </button>
          <button className={`${btn} hidden sm:inline-flex`} onClick={events.skipToEnd} disabled={ended}>
            <Icon name="skip" size={14} />Skip to end
          </button>
          <div className="hidden items-center gap-1 sm:flex" role="group" aria-label="Replay speed">
            {([1, 2, 4] as const).map((s) => (
              <button key={s} aria-pressed={speed === s} onClick={() => onSpeed(s)} className={`${btn} min-w-11 justify-center ${speed === s ? "border-ink bg-sunken" : ""}`}>{s}×</button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

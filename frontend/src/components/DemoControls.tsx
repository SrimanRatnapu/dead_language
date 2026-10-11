"use client";
import { useState } from "react";
import { killSpecialist, removeListing, resetDemo } from "@/lib/api";
import type { CaseEvents, Speed } from "@/lib/useCaseEvents";
import { Icon } from "./Icon";

interface Props {
  listingId: string | null;
  events: CaseEvents;
  speed: Speed;
  onSpeed: (s: Speed) => void;
}

// Playback controls sit in the page toolbar (always visible, never over content).
// Live-only demo actions live in a popover behind "Demo actions".
export function DemoControls({ listingId, events, speed, onSpeed }: Props) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const live = !events.controllable;

  async function run(label: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      setNote(null);
    } catch {
      setNote(`${label} failed. Check that the backend is running, then try again.`);
    }
  }

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
      {live && <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className={`${btn} text-muted`}>Demo actions</button>}
      {live && open && (
        <div className="bg-surface rise absolute right-0 top-full z-20 mt-2 flex w-64 flex-col gap-2 rounded-none border border-line p-3 shadow-[var(--shadow)]">
          <button className={btn} disabled={!live || !listingId} title={live ? "" : "Live cases only"} onClick={() => listingId && run("Remove listing", () => removeListing(listingId))}>
            Remove listing
          </button>
          <button className={btn} disabled={!live} title={live ? "" : "Live cases only"} onClick={() => run("Stop examiner", () => killSpecialist("deadlang-examiner-thorough"))}>
            Stop thorough examiner
          </button>
          <button className={btn} onClick={() => run("Reset", resetDemo)}>Reset demo</button>
          {!live && <p className="text-muted">Remove and stop apply to live cases only.</p>}
          {note && <p role="alert" className="rounded-none bg-red-tint px-3 py-2 text-red">{note}</p>}
        </div>
      )}
    </div>
  );
}

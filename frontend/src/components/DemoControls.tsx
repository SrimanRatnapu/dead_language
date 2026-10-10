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

// Hidden behind a toggle so the projector view stays clean.
export function DemoControls({ listingId, events, speed, onSpeed }: Props) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const live = !events.controllable;

  async function run(label: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      setNote(null);
    } catch {
      setNote(`${label} failed — is the backend running?`);
    }
  }

  const btn = "press flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 hover:border-ink";
  return (
    <div className="fixed bottom-20 right-4 z-10 flex flex-col items-end gap-2">
      {open && (
        <div className="glass rise flex w-64 flex-col gap-2 rounded-lg border border-line p-3 shadow-[var(--shadow)]">
          {events.controllable && (
            <>
              <div className="flex gap-1.5">
                <button className={btn} onClick={events.status === "paused" ? events.play : events.pause} disabled={events.status === "ended"}>
                  <Icon name={events.status === "paused" ? "play" : "pause"} size={14} />
                  {events.status === "paused" ? "Play" : "Pause"}
                </button>
                <button className={btn} onClick={events.skipToEnd} disabled={events.status === "ended"}>
                  <Icon name="skip" size={14} />Skip to end
                </button>
              </div>
              <div className="flex items-center gap-1.5" role="group" aria-label="Replay speed">
                {([1, 2, 4] as const).map((s) => (
                  <button key={s} aria-pressed={speed === s} onClick={() => onSpeed(s)} className={`${btn} ${speed === s ? "border-ink bg-sunken" : ""}`}>{s}×</button>
                ))}
              </div>
            </>
          )}
          <button className={btn} disabled={!live || !listingId} title={live ? "" : "Live cases only"} onClick={() => listingId && run("Remove listing", () => removeListing(listingId))}>
            Remove listing
          </button>
          <button className={btn} disabled={!live} title={live ? "" : "Live cases only"} onClick={() => run("Stop examiner", () => killSpecialist("deadlang-examiner-thorough"))}>
            Stop thorough examiner
          </button>
          <button className={btn} onClick={() => run("Reset", resetDemo)}>Reset demo</button>
          {note && <p className="text-red">{note}</p>}
        </div>
      )}
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className={`${btn} text-muted`}>Demo</button>
    </div>
  );
}

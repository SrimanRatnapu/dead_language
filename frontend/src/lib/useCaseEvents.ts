"use client";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { API_BASE } from "./api";
import { initialCaseState, reduce, type CaseState } from "./caseState";
import { loadReplay, parseJsonl } from "./stubs";
import { EVENT_TYPES, type Event } from "./types";

export type Speed = 1 | 2 | 4;
export type CaseSource =
  | { kind: "live"; caseId: string }
  | { kind: "replay"; name: string; speed: Speed }
  | { kind: "fixture"; speed?: Speed };

type Action = { type: "event"; event: Event } | { type: "events"; events: Event[] } | { type: "reset" };

function reducer(state: CaseState, a: Action): CaseState {
  if (a.type === "reset") return initialCaseState;
  return (a.type === "event" ? [a.event] : a.events).reduce(reduce, state);
}

const MAX_GAP_MS = 2500;
// Everything from the first of these onward is the agents' stage. It is held back until release() is called.
const AGENT_STAGE = new Set<string>(["round.started", "agent.thinking", "stance.posted", "claim.rejected", "case.ended", "budget.exceeded"]);

export interface CaseEvents {
  state: CaseState;
  status: "loading" | "playing" | "paused" | "ended" | "error";
  error: string | null;
  offline: boolean;
  controllable: boolean; // replay/fixture only
  held: boolean; // the examination is finished and the agents are waiting for release()
  release: (instant?: boolean) => void; // instant: show what already happened at once instead of at its original pace
  pause: () => void;
  play: () => void;
  skipToEnd: () => void;
}

export function useCaseEvents(source: CaseSource): CaseEvents {
  const [state, dispatch] = useReducer(reducer, initialCaseState);
  const [status, setStatus] = useState<CaseEvents["status"]>("loading");
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [held, setHeld] = useState(false);
  const ended = useRef(false); // the case.ended event has been shown
  const live = useRef(source.kind === "live");
  const gate = useRef({ open: false, buffer: [] as Event[] });

  const speedRef = useRef<Speed>(1);
  const speed = source.kind === "live" ? 1 : (source.speed ?? 1);
  useEffect(() => { speedRef.current = speed; }, [speed]);
  const pausedRef = useRef(false);
  const queue = useRef<{ events: Event[]; i: number }>({ events: [], i: 0 });
  const timer = useRef<number | undefined>(undefined);

  const key = source.kind === "live" ? `live:${source.caseId}` : source.kind === "replay" ? `replay:${source.name}` : "fixture";

  // Self-scheduling step lives in a ref so it can re-arm itself without referencing its own binding.
  const tickRef = useRef<() => void>(() => {});
  useEffect(() => {
    tickRef.current = () => {
      timer.current = undefined;
      const q = queue.current;
      if (pausedRef.current || q.i >= q.events.length) return;
      if (!gate.current.open && AGENT_STAGE.has(q.events[q.i].type)) return setHeld(true);
      const e = q.events[q.i++];
      dispatch({ type: "event", event: e });
      if (e.type === "case.ended") ended.current = true;
      if (q.i >= q.events.length) return live.current && !ended.current ? undefined : setStatus("ended"); // a live case keeps going after the backlog
      const gap = Math.max(0, Date.parse(q.events[q.i].at) - Date.parse(e.at));
      timer.current = window.setTimeout(() => tickRef.current(), Math.min(gap, MAX_GAP_MS) / speedRef.current);
    };
  }, []);
  const tick = useCallback(() => tickRef.current(), []);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    dispatch({ type: "reset" });
    // status/error start at "loading"/null; a new source remounts the page, so no synchronous reset here
    pausedRef.current = false;
    queue.current = { events: [], i: 0 };
    gate.current = { open: false, buffer: [] };
    ended.current = false;
    live.current = source.kind === "live";
    setHeld(false);

    if (source.kind === "live") {
      es = new EventSource(`${API_BASE}/api/cases/${source.caseId}/events`);
      // status flips to "playing" on the first event
      const onMsg = (m: MessageEvent<string>) => {
        const event = JSON.parse(m.data) as Event;
        const g = gate.current;
        if (!g.open && (g.buffer.length > 0 || AGENT_STAGE.has(event.type))) { g.buffer.push(event); setHeld(true); setStatus("playing"); return; }
        const q = queue.current;
        if (q.i < q.events.length) { q.events.push(event); return; } // still pacing the released backlog: queue behind it
        dispatch({ type: "event", event });
        setStatus("playing");
        if (event.type === "case.ended") {
          ended.current = true;
          es?.close();
          setStatus("ended");
        }
      };
      EVENT_TYPES.forEach((t) => es!.addEventListener(t, onMsg as EventListener));
      es.onerror = () => {
        // EventSource auto-reconnects (seq dedupe makes that safe); only surface a hard close.
        if (es?.readyState === EventSource.CLOSED && !ended.current) {
          setError("Lost connection to the backend.");
          setStatus("error");
        }
      };
    } else {
      const load =
        source.kind === "replay"
          ? loadReplay(source.name)
          : fetch("/replays/sample_case.jsonl").then(async (r) => ({ data: await parseJsonl(r), offline: true }));
      load
        .then(({ data, offline: off }) => {
          if (cancelled) return;
          setOffline(off);
          queue.current = { events: data, i: 0 };
          setStatus("playing");
          tick();
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : "Could not load replay");
          setStatus("error");
        });
    }
    return () => {
      cancelled = true;
      es?.close();
      clearTimeout(timer.current);
      timer.current = undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` captures the source identity; speed is read via ref
  }, [key, tick]);

  const pause = useCallback(() => {
    pausedRef.current = true;
    clearTimeout(timer.current);
    timer.current = undefined;
    setStatus((s) => (s === "playing" ? "paused" : s));
  }, []);

  const play = useCallback(() => {
    if (!pausedRef.current) return;
    pausedRef.current = false;
    setStatus("playing");
    tick();
  }, [tick]);

  const release = useCallback((instant = false) => {
    const g = gate.current;
    if (g.open) return;
    g.open = true;
    setHeld(false);
    if (!g.buffer.length) return;
    if (instant) { dispatch({ type: "events", events: g.buffer.splice(0) }); return; }
    // Play the backlog at the pace it happened (capped), so the agents' stage unfolds instead of landing all at once.
    queue.current = { events: g.buffer.splice(0), i: 0 };
    tick();
  }, [tick]);

  const skipToEnd = useCallback(() => {
    gate.current.open = true;
    setHeld(false);
    const q = queue.current;
    clearTimeout(timer.current);
    timer.current = undefined;
    if (q.i < q.events.length) dispatch({ type: "events", events: q.events.slice(q.i) });
    q.i = q.events.length;
    setStatus("ended");
  }, []);

  return { state, status, error, offline, controllable: source.kind !== "live", held, release, pause, play, skipToEnd };
}

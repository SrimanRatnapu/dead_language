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

export interface CaseEvents {
  state: CaseState;
  status: "loading" | "playing" | "paused" | "ended" | "error";
  error: string | null;
  offline: boolean;
  controllable: boolean; // replay/fixture only
  pause: () => void;
  play: () => void;
  skipToEnd: () => void;
}

export function useCaseEvents(source: CaseSource): CaseEvents {
  const [state, dispatch] = useReducer(reducer, initialCaseState);
  const [status, setStatus] = useState<CaseEvents["status"]>("loading");
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

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
      const e = q.events[q.i++];
      dispatch({ type: "event", event: e });
      if (q.i >= q.events.length) return setStatus("ended");
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

    if (source.kind === "live") {
      es = new EventSource(`${API_BASE}/api/cases/${source.caseId}/events`);
      // status flips to "playing" on the first event
      const onMsg = (m: MessageEvent<string>) => {
        const event = JSON.parse(m.data) as Event;
        dispatch({ type: "event", event });
        setStatus("playing");
        if (event.type === "case.ended") {
          es?.close();
          setStatus("ended");
        }
      };
      EVENT_TYPES.forEach((t) => es!.addEventListener(t, onMsg as EventListener));
      es.onerror = () => {
        // EventSource auto-reconnects (seq dedupe makes that safe); only surface a hard close.
        if (es?.readyState === EventSource.CLOSED) {
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

  const skipToEnd = useCallback(() => {
    const q = queue.current;
    clearTimeout(timer.current);
    timer.current = undefined;
    if (q.i < q.events.length) dispatch({ type: "events", events: q.events.slice(q.i) });
    q.i = q.events.length;
    setStatus("ended");
  }, []);

  return { state, status, error, offline, controllable: source.kind !== "live", pause, play, skipToEnd };
}

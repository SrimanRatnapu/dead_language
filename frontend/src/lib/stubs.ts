// Offline fallbacks: the backend may be down (or not built yet). Static copies live in public/.
import * as api from "./api";
import type { Event, EvalResults, ListingRow } from "./types";

export interface Loaded<T> {
  data: T;
  offline: boolean;
}

async function staticJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function parseJsonl(res: Response): Promise<Event[]> {
  if (!res.ok) throw new Error(`replay not found: ${res.status}`);
  const text = await res.text();
  return text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l) as Event);
}

async function withFallback<T>(live: () => Promise<T>, fallback: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { data: await live(), offline: false };
  } catch {
    return { data: await fallback(), offline: true };
  }
}

export const loadListings = () =>
  withFallback(api.getListings, () => staticJson<ListingRow[]>("/stub/listings.json"));

export const loadReplays = () =>
  withFallback(api.getReplays, () => staticJson<string[]>("/replays/index.json"));

export const loadReplay = (name: string) =>
  withFallback(
    () => api.getReplay(name),
    async () => parseJsonl(await fetch(`/replays/${name}.jsonl`)),
  );

export const loadEval = () =>
  withFallback(api.getEval, () => staticJson<EvalResults & { _stub?: boolean }>("/stub/eval.json"));

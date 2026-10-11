import type { BatchItem, BatchStart, ListingChange, MarketStats, Metrics, CaseFile, Event, EvalResults, Listing, ListingRow, Seller } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const getListings = () => req<ListingRow[]>("/api/listings?sort=triage");
export const getListing = (id: string) => req<{ listing: Listing; seller: Seller }>(`/api/listings/${id}`);
export const startCase = (listingId: string) =>
  post<{ case_id: string }>("/api/cases", { listing_id: listingId });
export const getCaseFile = (caseId: string) => req<CaseFile>(`/api/cases/${caseId}/casefile`);
export const removeListing = (id: string) =>
  post<{ removed: string; relisted_as: string | null }>("/api/demo/remove-listing", { listing_id: id });
export const killSpecialist = (name: string) => post<{ ok: boolean }>("/api/demo/kill-specialist", { name });
export const resetDemo = () => post<{ ok: boolean }>("/api/demo/reset");
export const getReplays = () => req<string[]>("/api/replays");
export const getReplay = (name: string) => req<Event[]>(`/api/replays/${name}`);
export const getEval = () => req<EvalResults>("/api/eval");
export const getBatch = (id: string) => req<BatchStart>(`/api/batches/${id}`);
export const startBatch = (body: { source: "demo" | "live"; query?: string; sweep?: string; cap?: number }) =>
  post<BatchStart>("/api/batches", body);
export const batchEventsUrl = (id: string) => `${API_BASE}/api/batches/${id}/events`;
export const getHealth = () => req<{ transport: string; problems: string[] }>("/api/health");
export const getMetrics = () => req<Metrics>("/api/metrics");
export const getMarket = () => req<MarketStats>("/api/market");
export const refreshNow = () => post<ListingChange[]>("/api/refresh");
export const imageUrl = (relPath: string) => `${API_BASE}/api/images/${relPath}`;

/** Review one listing now. Throws the server's message (bad link, not found, eBay unavailable). */
export async function addToQueue(ref: string): Promise<{ batch_id: string; source_mode: BatchStart["source_mode"]; item: BatchItem; new_batch: boolean }> {
  const res = await fetch(`${API_BASE}/api/queue/add`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ref }) });
  if (!res.ok) {
    const d = (await res.json().catch(() => null))?.detail;
    throw new Error(typeof d === "string" ? d : "That did not work. Check the backend log.");
  }
  return res.json();
}

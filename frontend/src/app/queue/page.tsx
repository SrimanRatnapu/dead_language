"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/Icon";
import { Photo } from "@/components/Photo";
import { batchEventsUrl, getListing, getHealth, getListings, imageUrl, startBatch } from "@/lib/api";
import type { BatchEvent, BatchItem, BatchStart, Listing } from "@/lib/types";

const MAX_CAP = 50; // server rejects more (422); keep in sync with MAX_LIVE_CAP in api/server.py

type Mark = { icon: IconName; label: string; tone: string };
function markFor(i: BatchItem): Mark | null {
  if (i.status === "error") return { icon: "system_notice", label: i.error ?? "Error", tone: "text-red" };
  if (i.status === "screened_out") return { icon: "check", label: "Screened out", tone: "text-green" };
  if (i.status !== "done") return null;
  if (i.outcome === "FILE") return { icon: "flag", label: "Flagged for review", tone: "text-cobalt-ink" };
  if (i.outcome === "CONTESTED") return { icon: "split", label: "Contested: a person decides", tone: "text-cobalt-ink" };
  if (i.outcome === "WATCHLIST") return { icon: "clock", label: "Watchlist", tone: "text-muted" };
  return { icon: "check", label: "Cleared", tone: "text-green" };
}
const WORKING: Partial<Record<BatchItem["status"], string>> = { queued: "Queued", triaging: "Checking", deliberating: "Agents working" };

export default function Queue() {
  const [items, setItems] = useState<BatchItem[]>([]);
  const [mode, setMode] = useState<BatchStart["source_mode"] | null>(null);
  const [listings, setListings] = useState<Record<string, Listing>>({});
  const [query, setQuery] = useState("");
  const [cap, setCap] = useState(25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);
  const es = useRef<EventSource | null>(null);

  useEffect(() => {
    getListings().then((rows) => setListings(Object.fromEntries(rows.map((r) => [r.listing.id, r.listing])))).catch(() => {});
    getHealth().then((h) => setProblems(h.problems)).catch(() => {});
    return () => es.current?.close();
  }, []);
  const running = items.some((i) => !["done", "screened_out", "error"].includes(i.status));
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [running]);

  async function run(source: "demo" | "live") {
    setBusy(true); setError(null); es.current?.close();
    try {
      const b = await startBatch(source === "live" ? { source, query, cap } : { source });
      setItems(b.items); setMode(b.source_mode); setStartedAt(Date.now()); setNow(Date.now());
      b.items.forEach((i) => getListing(i.listing_id).then((r) => setListings((l) => ({ ...l, [r.listing.id]: r.listing }))).catch(() => {}));
      const src = new EventSource(batchEventsUrl(b.batch_id));
      es.current = src;
      src.addEventListener("batch.item", (m) => {
        const e: BatchEvent = JSON.parse((m as MessageEvent).data);
        setItems((cur) => cur.map((i) => i.listing_id === e.listing_id ? { ...i, status: e.status, case_id: e.case_id, outcome: e.outcome ?? i.outcome } : i));
        setNow(Date.now());
      });
      src.onerror = () => src.close(); // server ends the stream when every item is finished
    } catch (e) {
      setError(source === "live" ? "Live fetch is not available yet." : "The review service is offline. Start the backend and try again.");
    } finally { setBusy(false); }
  }

  const count = (f: (i: BatchItem) => boolean) => items.filter(f).length;
  const secs = startedAt ? Math.round((now - startedAt) / 1000) : 0;
  const summary: [string, number][] = [
    ["flagged", count((i) => i.outcome === "FILE")], ["contested", count((i) => i.outcome === "CONTESTED")],
    ["watchlist", count((i) => i.outcome === "WATCHLIST")], ["cleared", count((i) => i.outcome === "DISMISS" || i.status === "screened_out")],
    ["errors", count((i) => i.status === "error")],
  ];
  const btn = "press min-h-11 px-4 py-2.5 font-semibold disabled:opacity-40";

  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-5xl px-5 py-6 sm:px-8">
        <header className="border-b border-line pb-3"><h1 className="text-xl font-semibold tracking-tight">Queue</h1></header>
        <section aria-label="Start a batch" className="flex flex-wrap items-end gap-x-6 gap-y-3 border-b border-line py-4">
          <button onClick={() => run("demo")} disabled={busy || running} className={`${btn} bg-ink text-surface hover:bg-cobalt`}>Run demo set</button>
          <form onSubmit={(e) => { e.preventDefault(); run("live"); }} className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-muted">Search<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="bone netsuke" className="mt-1 block min-h-11 w-56 border border-line bg-surface px-3 text-base text-ink" /></label>
            <label className="text-sm text-muted">Max items (up to {MAX_CAP})<input type="number" min={1} max={MAX_CAP} value={cap} onChange={(e) => setCap(Math.min(MAX_CAP, Math.max(1, Number(e.target.value) || 1)))} className="mt-1 block min-h-11 w-24 border border-line bg-surface px-3 text-base text-ink" /></label>
            <button type="submit" disabled={busy || running || !query.trim()} className={`${btn} border border-ink hover:bg-surface`}>Fetch live</button>
          </form>
        </section>
        {problems.length > 0 && <p role="alert" className="border-b border-amber/40 bg-amber-tint px-3 py-2 text-ink">{problems.join(". ")}. Reviews will stall until it is running.</p>}
        {error && <p role="alert" className="border-b border-red/30 bg-red-tint px-3 py-2 text-red">{error}</p>}
        {items.length > 0 && <>
          <p className="mono flex flex-wrap gap-x-4 border-b border-line py-2 text-sm text-muted" aria-live="polite">
            {summary.map(([k, n]) => <span key={k}>{n} {k}</span>)}<span>{secs}s</span>
            {mode === "recorded" && <span className="text-ink">recorded data</span>}
          </p>
          <ul className="divide-y divide-line border-b border-line">
            {items.map((i) => {
              const l = listings[i.listing_id]; const m = markFor(i);
              const body = <>
                <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? i.listing_id} className="size-14 w-full" />
                <span className="min-w-0"><span className="block line-clamp-2 font-semibold">{l?.title ?? i.listing_id}</span>
                  <span className="block text-sm text-muted">{l ? `$${l.price_usd.toLocaleString()} · ` : ""}<span className="mono text-xs">{l?.origin === "live" ? "Live" : "Demo"}</span></span></span>
                <span className={`inline-flex items-center justify-end gap-2 text-sm font-semibold ${m?.tone ?? "text-muted"}`}>
                  {m ? <><Icon name={m.icon} size={18} />{m.label}</>
                     : <><span className="typing flex gap-1" aria-hidden><span /><span /><span /></span>{WORKING[i.status]}{i.status === "deliberating" && secs > 0 ? ` · ${secs}s` : ""}</>}
                </span></>;
              const row = "grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 py-3";
              return <li key={i.listing_id}>{i.case_id && i.status === "done"
                ? <Link href={`/case/${i.case_id}`} className={`press ${row} hover:bg-surface/70`}>{body}</Link>
                : <div className={row}>{body}</div>}</li>;
            })}
          </ul></>}
        {items.length === 0 && !error && <p className="py-6 text-muted">Run the demo set to watch listings move through screening and review.</p>}
      </div>
    </main>
  );
}

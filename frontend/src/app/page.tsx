"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/Icon";
import { Photo } from "@/components/Photo";
import { ListingCard } from "@/components/ListingCard";
import { DEMO_CASES } from "@/lib/demoCases";
import { batchEventsUrl, getBatch, getCaseFile, getListing, getHealth, imageUrl, startBatch } from "@/lib/api";
import { loadListings } from "@/lib/stubs";
import type { BatchEvent, BatchItem, BatchStart, Listing, ListingRow } from "@/lib/types";

const MAX_CAP = 50; // server rejects more (422); keep in sync with MAX_LIVE_CAP in api/server.py

type Mark = { icon: IconName; label: string; tone: string };
function markFor(i: BatchItem): Mark | null {
  if (i.status === "error") return { icon: "system_notice", label: i.error ?? "Error", tone: "text-red" };
  if (i.status === "screened_out") return { icon: "check", label: "Screened out", tone: "text-green" };
  if (i.status !== "done") return null;
  if (i.outcome === "FILE") return { icon: "flag", label: "Flagged: file for review", tone: "text-red" };
  if (i.outcome === "CONTESTED") return { icon: "split", label: "Contested: a person decides", tone: "text-amber-ink" };
  if (i.outcome === "WATCHLIST") return { icon: "clock", label: "Watchlist: check again later", tone: "text-cobalt-ink" };
  return { icon: "check", label: "Dismissed: looks legal", tone: "text-green" };
}
const WORKING: Partial<Record<BatchItem["status"], string>> = { queued: "Queued", triaging: "Checking", deliberating: "Agents working" };

export default function Cases() {
  const [items, setItems] = useState<BatchItem[]>([]);
  const [mode, setMode] = useState<BatchStart["source_mode"] | null>(null);
  const [listings, setListings] = useState<Record<string, Listing>>({});
  const [shown, setShown] = useState(24);
  const [rows, setRows] = useState<ListingRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [cap, setCap] = useState(25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);
  const es = useRef<EventSource | null>(null);
  const batchId = useRef<string | null>(null);
  const itemsRef = useRef<BatchItem[]>([]);
  useEffect(() => { itemsRef.current = items; }, [items]);

  useEffect(() => {
    // Coming back from another page: reload the batch that was running or finished.
    const saved = sessionStorage.getItem("dl_batch");
    if (saved) {
      const { id, mode: m, startedAt: t } = JSON.parse(saved);
      getBatch(id).then((b) => {
        batchId.current = id; setItems(b.items); setMode(m); setStartedAt(t); setNow(Date.now());
        b.items.forEach((i) => getListing(i.listing_id).then((r) => setListings((l) => ({ ...l, [r.listing.id]: r.listing }))).catch(() => {}));
      }).catch(() => sessionStorage.removeItem("dl_batch"));
    }
    loadListings().then(({ data }) => { setRows(data); setListings(Object.fromEntries(data.map((x) => [x.listing.id, x.listing]))); }).catch(() => setRows([]));
    getHealth().then((h) => setProblems(h.problems)).catch(() => {});
    return () => es.current?.close();
  }, []);
  const running = items.some((i) => !["done", "screened_out", "error"].includes(i.status));
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    // The event stream can drop (network blip, dev-server reload); re-read the batch so rows never stay on "Agents working".
    const p = setInterval(() => { if (batchId.current) getBatch(batchId.current).then((b) => setItems(b.items)).catch(() => {}); }, 4000);
    // A finished case file is proof the row is done, whatever the batch stream last said.
    const c = setInterval(() => itemsRef.current.forEach((i) => {
      if (i.case_id && !["done", "error", "screened_out"].includes(i.status))
        getCaseFile(i.case_id).then((cf) => setItems((cur) => cur.map((x) => x.listing_id === i.listing_id ? { ...x, status: "done", outcome: cf.outcome } : x))).catch(() => {});
    }), 4000);
    return () => { clearInterval(t); clearInterval(p); clearInterval(c); };
  }, [running]);

  async function run(source: "demo" | "live") {
    setBusy(true); setError(null); es.current?.close();
    try {
      const b = await startBatch(source === "live" ? { source, query, cap } : { source });
      batchId.current = b.batch_id; sessionStorage.setItem("dl_batch", JSON.stringify({ id: b.batch_id, mode: b.source_mode, startedAt: Date.now() })); setItems(b.items); setMode(b.source_mode); setStartedAt(Date.now()); setNow(Date.now());
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
      setError(source === "live" ? "Live fetch failed. Try again, or check the backend log." : "The review service is offline. Start the backend and try again.");
    } finally { setBusy(false); }
  }

  const count = (f: (i: BatchItem) => boolean) => items.filter(f).length;
  const secs = startedAt ? Math.round((now - startedAt) / 1000) : 0;
  const summary: [string, number][] = [
    ["flagged", count((i) => i.outcome === "FILE")], ["contested", count((i) => i.outcome === "CONTESTED")],
    ["watchlist", count((i) => i.outcome === "WATCHLIST")], ["dismissed", count((i) => i.outcome === "DISMISS" || i.status === "screened_out")],
    ["errors", count((i) => i.status === "error")],
  ];
  const btn = "press min-h-11 px-4 py-2.5 font-semibold disabled:opacity-40";

  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-7xl px-5 py-6 sm:px-8">
        <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line pb-3"><h1 className="text-xl font-semibold tracking-tight">Cases</h1><p className="text-sm text-muted">Run a batch, replay a recorded review, or open any listing.</p></header>
        <section aria-label="Start a batch" className="flex flex-wrap items-end gap-x-6 gap-y-3 border-b border-line py-4">
          <button onClick={() => run("demo")} disabled={busy || running} className={`${btn} bg-ink text-surface hover:bg-cobalt`}>Run demo set</button>
          <form onSubmit={(e) => { e.preventDefault(); run("live"); }} className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-muted">Search<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="bone netsuke" className="mt-1 block min-h-11 w-56 border border-line bg-surface px-3 text-base text-ink" /></label>
            <label className="text-sm text-muted">Max items (up to {MAX_CAP})<input type="number" min={1} max={MAX_CAP} value={cap} onChange={(e) => setCap(Math.min(MAX_CAP, Math.max(1, Number(e.target.value) || 1)))} className="mt-1 block min-h-11 w-24 border border-line bg-surface px-3 text-base text-ink" /></label>
            <button type="submit" disabled={busy || running || !query.trim()} className={`${btn} border border-ink hover:bg-surface`}>Fetch live</button>
          </form>
        </section>
        {problems.length > 0 && <p role="alert" className="border-b border-amber/40 bg-amber-tint px-3 py-2 text-ink">{problems.join(". ")}. Reviews will stall until it is running.</p>}
        {busy && <p role="status" className="border-b border-line py-2 text-muted">Fetching listings and photos from eBay. This can take up to a minute.</p>}
        {error && <p role="alert" className="border-b border-red/30 bg-red-tint px-3 py-2 text-red">{error}</p>}
        {items.length > 0 && <>
          <p className="mono flex flex-wrap gap-x-4 border-b border-line py-2 text-sm text-muted" aria-live="polite">
            {summary.map(([k, n]) => <span key={k}>{n} {k}</span>)}<span>{secs}s</span>
            {mode === "recorded" && <span className="text-ink">recorded data</span>}
          </p>
          <ul className="-mx-3 divide-y divide-line border-b border-line">
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
              const row = "grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 px-3 py-3";
              return <li key={i.listing_id}>{i.case_id
                ? <Link href={`/case/${i.case_id}?stage=agents`} className={`press ${row} hover:bg-surface/70`}>{body}</Link>
                : <div className={row}>{body}</div>}</li>;
            })}
          </ul></>}
        <section aria-labelledby="recorded" className="mt-8">
          <h2 id="recorded" className="text-lg font-semibold tracking-tight">Recorded reviews</h2>
          <p className="text-sm text-muted">Four finished reviews. They play back without the review service.</p>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {DEMO_CASES.map((c) => {
              const l = listings[c.listingId];
              return (
                <li key={c.key}>
                  <Link href={`/replay/${c.replay}`} className="press group grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 py-3 hover:bg-surface/70">
                    <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={c.label} className="size-14 w-full" />
                    <span className="min-w-0"><span className="block font-semibold">{c.label}</span><span className="block text-sm text-muted">{c.blurb}</span></span>
                    <span className="text-sm font-semibold text-cobalt-ink group-hover:underline">Replay →</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
        <section aria-labelledby="all" className="mt-10">
          <h2 id="all" className="text-lg font-semibold tracking-tight">All listings{rows ? ` (${rows.length})` : ""}</h2>
          <p className="text-sm text-muted">Open one to read it, then run a review on it.</p>
          {rows === null ? <p className="mt-6 text-muted">Loading listings…</p>
            : rows.length === 0 ? <p className="mt-6 text-muted">No listings found.</p>
            : <div className="mt-5 grid gap-x-5 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">{rows.slice(0, shown).map((row) => <ListingCard key={row.listing.id} row={row} />)}</div>}
          {rows && rows.length > shown && <button onClick={() => setShown((n) => n + 48)} className="press mt-8 min-h-11 border border-ink px-4 py-2.5 font-semibold hover:bg-surface">Show more ({rows.length - shown} left)</button>}
        </section>
      </div>
    </main>
  );
}

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
  if (i.outcome === "FILE") return { icon: "flag", label: "Approve or reject", tone: "text-red" };
  if (i.outcome === "CONTESTED") return { icon: "split", label: "Decide", tone: "text-amber-ink" };
  if (i.outcome === "WATCHLIST") return { icon: "clock", label: "Watching", tone: "text-cobalt-ink" };
  return { icon: "check", label: "Dismissed", tone: "text-green" };
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
  const btn = "press min-h-11 px-4 py-2.5 font-semibold disabled:opacity-40";
  const terminal = (i: BatchItem) => ["done", "screened_out", "error"].includes(i.status);
  const GROUPS: { key: string; title: string; hint: string; test: (i: BatchItem) => boolean }[] = [
    { key: "decide", title: "Waiting on you", hint: "Approve or decide before anything is sent.", test: (i) => i.status === "done" && (i.outcome === "FILE" || i.outcome === "CONTESTED") },
    { key: "working", title: "In review", hint: "", test: (i) => !terminal(i) },
    { key: "watch", title: "Watchlist", hint: "Not enough to file. Listed until something changes.", test: (i) => i.status === "done" && i.outcome === "WATCHLIST" },
    { key: "cleared", title: "Cleared", hint: "Looked legal. Logged, no action.", test: (i) => i.status === "screened_out" || (i.status === "done" && i.outcome === "DISMISS") },
    { key: "error", title: "Errors", hint: "These did not finish. Run them again.", test: (i) => i.status === "error" },
  ];
  const waiting = count(GROUPS[0].test);

  const Row = ({ i }: { i: BatchItem }) => {
    const l = listings[i.listing_id]; const m = markFor(i);
    const body = <>
      <span className="serial hidden w-24 sm:block">{i.case_id ?? "queued"}</span>
      <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? i.listing_id} className="size-14 w-full" />
      <span className="min-w-0"><span className="block line-clamp-2 font-semibold">{l?.title ?? i.listing_id}</span>
        <span className="block text-sm text-muted">{l ? `$${l.price_usd.toLocaleString()} · ` : ""}{l?.origin === "live" ? "Live listing" : "Demo listing"}</span></span>
      <span className={`inline-flex items-center justify-end gap-2 text-sm font-semibold ${m?.tone ?? "text-muted"}`}>
        {m ? <><Icon name={m.icon} size={18} />{m.label}</>
           : <><span className="typing flex gap-1" aria-hidden><span /><span /><span /></span>{WORKING[i.status]}{i.status === "deliberating" && secs > 0 ? ` · ${secs}s` : ""}</>}
      </span></>;
    const row = "grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 px-3 py-3 sm:grid-cols-[6rem_3.5rem_1fr_auto]";
    return i.case_id
      ? <Link href={`/case/${i.case_id}?stage=agents`} className={`press ${row} hover:bg-surface`}>{body}</Link>
      : <div className={row}>{body}</div>;
  };

  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-ink pb-5">
          <div>
            <h1 className="serif text-4xl font-extrabold leading-none tracking-[-0.03em]">Review desk</h1>
            <p className="mt-2 text-muted" aria-live="polite">
              {items.length === 0 ? "Nothing loaded yet." : waiting > 0 ? `${waiting} ${waiting === 1 ? "case needs" : "cases need"} your decision.` : running ? "Agents are working." : "Nothing waiting on you."}
              {items.length > 0 && <span className="serial ml-3">{items.length} loaded · {secs}s{mode === "recorded" ? " · recorded data" : ""}</span>}
            </p>
          </div>
          <section aria-label="Load listings" className="flex flex-wrap items-end gap-x-4 gap-y-3">
            <button onClick={() => run("demo")} disabled={busy || running} className={`${btn} bg-ink text-surface hover:bg-ink-2`}>Run demo set</button>
            <form onSubmit={(e) => { e.preventDefault(); run("live"); }} className="flex flex-wrap items-end gap-3">
              <label className="text-sm text-muted">Search live listings<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="bone netsuke" className="mt-1 block min-h-11 w-52 border border-line bg-surface px-3 text-base text-ink" /></label>
              <label className="text-sm text-muted">Max<input type="number" min={1} max={MAX_CAP} value={cap} onChange={(e) => setCap(Math.min(MAX_CAP, Math.max(1, Number(e.target.value) || 1)))} aria-label={`Max items, up to ${MAX_CAP}`} className="mt-1 block min-h-11 w-20 border border-line bg-surface px-3 text-base text-ink" /></label>
              <button type="submit" disabled={busy || running || !query.trim()} className={`${btn} border border-ink hover:bg-surface`}>Fetch live</button>
            </form>
          </section>
        </header>
        {problems.length > 0 && <p role="alert" className="border-b border-amber/60 bg-amber-tint px-3 py-2 text-ink">{problems.join(". ")}. Reviews will stall until it is running.</p>}
        {busy && <p role="status" className="border-b border-line py-2 text-muted">Fetching listings and photos from eBay. This can take up to a minute.</p>}
        {error && <p role="alert" className="border-b border-red/30 bg-red-tint px-3 py-2 text-red">{error}</p>}

        {items.length === 0 && !busy && (
          <section className="relative my-8 overflow-hidden border border-line bg-surface px-6 py-10">
            <span className="lattice text-ink/[0.07]" aria-hidden />
            <p className="serif relative max-w-[28ch] text-2xl font-bold leading-snug">The desk is empty. Run the demo set, or search live listings.</p>
            <p className="relative mt-2 max-w-[56ch] text-muted">Cases land in the group that says what you have to do with them. Anything the agents file or contest waits here for you.</p>
          </section>
        )}

        {GROUPS.map((g) => {
          const rows = items.filter(g.test);
          if (rows.length === 0) return null;
          return (
            <section key={g.key} aria-labelledby={`g-${g.key}`} className="mt-8">
              <div className="flex flex-wrap items-baseline gap-x-4 border-b border-ink pb-1.5">
                <h2 id={`g-${g.key}`} className="serif text-xl font-bold">{g.title}</h2>
                <span className="serial">{rows.length}</span>
                {g.hint && <p className="text-sm text-muted">{g.hint}</p>}
              </div>
              <ul className="-mx-3 divide-y divide-line">{rows.map((i) => <li key={i.listing_id}>{Row({ i })}</li>)}</ul>
            </section>
          );
        })}

        <section aria-labelledby="recorded" className="mt-12">
          <h2 id="recorded" className="serif border-b border-ink pb-1.5 text-xl font-bold">Recorded reviews</h2>
          <p className="mt-2 text-sm text-muted">Four finished reviews. They play back without the review service.</p>
          <ul className="mt-2 divide-y divide-line">
            {DEMO_CASES.map((c) => {
              const l = listings[c.listingId];
              return (
                <li key={c.key}>
                  <Link href={`/replay/${c.replay}`} className="press group grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 py-3 hover:bg-surface">
                    <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={c.label} className="size-14 w-full" />
                    <span className="min-w-0"><span className="block font-semibold">{c.label}</span><span className="block text-sm text-muted">{c.blurb}</span></span>
                    <span className="text-sm font-semibold text-cobalt-ink group-hover:underline">Replay →</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
        <section aria-labelledby="all" className="mt-12">
          <h2 id="all" className="serif border-b border-ink pb-1.5 text-xl font-bold">All listings{rows ? ` (${rows.length})` : ""}</h2>
          <p className="mt-2 text-sm text-muted">Open one to read it, then run a review on it.</p>
          {rows === null ? <p className="mt-6 text-muted">Loading listings…</p>
            : rows.length === 0 ? <p className="mt-6 text-muted">No listings found.</p>
            : <div className="mt-5 grid gap-x-5 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">{rows.slice(0, shown).map((row) => <ListingCard key={row.listing.id} row={row} />)}</div>}
          {rows && rows.length > shown && <button onClick={() => setShown((n) => n + 48)} className="press mt-8 min-h-11 border border-ink px-4 py-2.5 font-semibold hover:bg-surface">Show more ({rows.length - shown} left)</button>}
        </section>
      </div>
    </main>
  );
}

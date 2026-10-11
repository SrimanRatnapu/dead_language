"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/Icon";
import { Photo } from "@/components/Photo";
import { ListingCard } from "@/components/ListingCard";
import { DEMO_CASES } from "@/lib/demoCases";
import { batchEventsUrl, getBatch, getCaseFile, getListing, getHealth, imageUrl, startBatch, getMetrics } from "@/lib/api";
import { loadListings } from "@/lib/stubs";
import type { Metrics, BatchEvent, BatchItem, BatchStart, Listing, ListingRow } from "@/lib/types";

// Names match SWEEPS in backend marketplace/live.py: listings by eBay category and price floor, newest first, no keyword.
const SWEEPS = [
  { key: "netsuke", label: "Netsuke and carvings" },
  { key: "figures", label: "Figures and statues" },
  { key: "bracelets", label: "Bracelets" },
];
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
// Why a row is on the desk when nobody searched for it, or what a flagged row set in motion.
function followUpNote(i: BatchItem): string | null {
  if (i.found_via === "seller") return `Same seller as ${i.parent ?? "a flagged listing"}`;
  if (i.found_via === "keyword") return `Title shares \u201c${i.term}\u201d with ${i.parent ?? "a flagged listing"}`;
  if (i.follow_up?.state === "searching") return "Finding related listings\u2026";
  if (i.follow_up?.state === "done" && i.follow_up.added > 0) return `${i.follow_up.added} related ${i.follow_up.added === 1 ? "listing" : "listings"} added to the desk`;
  return null;
}

export default function Cases() {
  const [items, setItems] = useState<BatchItem[]>([]);
  const [mode, setMode] = useState<BatchStart["source_mode"] | null>(null);
  const [listings, setListings] = useState<Record<string, Listing>>({});
  const [shown, setShown] = useState(24);
  const [rows, setRows] = useState<ListingRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [sweep, setSweep] = useState("netsuke"); // "" = keyword search
  const [source, setSource] = useState<string | null>(null); // what the current batch was fetched by, for the header
  const [cap, setCap] = useState(25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);
  const [m, setM] = useState<Metrics | null>(null);
  const es = useRef<EventSource | null>(null);
  const batchId = useRef<string | null>(null);
  const itemsRef = useRef<BatchItem[]>([]);
  useEffect(() => { itemsRef.current = items; }, [items]);
  // Rows can join a batch after it starts (follow-up listings): load any listing a row still lacks.
  const asked = useRef(new Set<string>());
  useEffect(() => {
    items.forEach((i) => {
      if (listings[i.listing_id] || asked.current.has(i.listing_id)) return;
      asked.current.add(i.listing_id);
      getListing(i.listing_id).then((r) => setListings((l) => ({ ...l, [r.listing.id]: r.listing }))).catch(() => { asked.current.delete(i.listing_id); });
    });
  }, [items, listings]);

  useEffect(() => {
    // Coming back from another page: reload the batch that was running or finished.
    const saved = sessionStorage.getItem("dl_batch");
    if (saved) {
      const { id, mode: m, startedAt: t, source: src } = JSON.parse(saved);
      getBatch(id).then((b) => {
        batchId.current = id; setItems(b.items); setMode(m); setStartedAt(t); setSource(src ?? null); setNow(Date.now());
      }).catch(() => sessionStorage.removeItem("dl_batch"));
    }
    loadListings().then(({ data }) => { setRows(data); setListings(Object.fromEntries(data.map((x) => [x.listing.id, x.listing]))); }).catch(() => setRows([]));
    getMetrics().then(setM).catch(() => {});
    getHealth().then((h) => setProblems(h.problems)).catch(() => {});
    return () => es.current?.close();
  }, []);
  const searching = items.some((i) => i.follow_up?.state === "searching"); // a flagged listing's related listings are still being fetched
  const running = searching || items.some((i) => !["done", "screened_out", "error"].includes(i.status));
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
      const b = await startBatch(source === "live" ? (sweep ? { source, sweep, cap } : { source, query, cap }) : { source });
      const label = source === "demo" ? "Demo set" : sweep ? SWEEPS.find((w) => w.key === sweep)!.label : `\u201c${query.trim()}\u201d`;
      setSource(label);
      batchId.current = b.batch_id; sessionStorage.setItem("dl_batch", JSON.stringify({ id: b.batch_id, mode: b.source_mode, startedAt: Date.now(), source: label })); setItems(b.items); setMode(b.source_mode); setStartedAt(Date.now()); setNow(Date.now());
      const src = new EventSource(batchEventsUrl(b.batch_id));
      es.current = src;
      src.addEventListener("batch.item", (m) => {
        const e: BatchEvent = JSON.parse((m as MessageEvent).data);
        setItems((cur) => cur.some((i) => i.listing_id === e.listing_id)
          ? cur.map((i) => i.listing_id === e.listing_id ? { ...i, status: e.status, case_id: e.case_id, outcome: e.outcome ?? i.outcome, follow_up: e.follow_up ?? i.follow_up } : i)
          // A listing the batch did not start with: a follow-up fetch added it. Give it a row.
          : [...cur, { listing_id: e.listing_id, case_id: e.case_id, status: e.status, triage: null, outcome: e.outcome ?? null, error: null, found_via: e.found_via ?? null, term: e.term ?? null, parent: e.parent ?? null, follow_up: null }]);
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
  const GROUPS: { key: string; title: string; test: (i: BatchItem) => boolean }[] = [
    { key: "decide", title: "Waiting on you", test: (i) => i.status === "done" && (i.outcome === "FILE" || i.outcome === "CONTESTED") },
    { key: "working", title: "In review", test: (i) => !terminal(i) },
    { key: "watch", title: "Watchlist", test: (i) => i.status === "done" && i.outcome === "WATCHLIST" },
    { key: "cleared", title: "Cleared", test: (i) => i.status === "screened_out" || (i.status === "done" && i.outcome === "DISMISS") },
    { key: "error", title: "Errors", test: (i) => i.status === "error" },
  ];
  const waiting = count(GROUPS[0].test);
  const added = count((i) => !!i.found_via); // follow-up listings the system queued itself

  const Row = ({ i }: { i: BatchItem }) => {
    const l = listings[i.listing_id]; const m = markFor(i); const note = followUpNote(i);
    const body = <>
      <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? i.listing_id} className="size-14 w-full" />
      <span className="min-w-0"><span className="block line-clamp-2 font-semibold">{l?.title ?? i.listing_id}</span>
        <span className="block text-sm text-muted">{l ? `$${l.price_usd.toLocaleString()} · ` : ""}{l?.origin === "live" || i.found_via ? "Live listing" : "Demo listing"}</span>
        {note && <span className="block text-sm text-cobalt-ink">{i.found_via && <b className="mr-2 border border-cobalt-ink px-1.5 text-xs uppercase">Added</b>}{note}</span>}</span>
      <span className={`inline-flex items-center justify-end gap-2 text-sm font-semibold ${m?.tone ?? "text-muted"}`}>
        {m ? <><Icon name={m.icon} size={18} />{m.label}</>
           : <><span className="typing flex gap-1" aria-hidden><span /><span /><span /></span>{WORKING[i.status]}{i.status === "deliberating" && secs > 0 ? ` · ${secs}s` : ""}</>}
      </span></>;
    const row = `${m ? "" : "scan "}relative grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 px-3 py-3`;
    return i.case_id
      ? <Link href={`/case/${i.case_id}?stage=agents`} className={`press ${row} hover:bg-surface`}>{body}</Link>
      : <div className={row}>{body}</div>;
  };

  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-6 border-b border-ink pb-6">
          <div>
            <h1 className="serif text-4xl leading-none">Review desk</h1>
            <p className="mt-2 text-muted" aria-live="polite">
              {items.length === 0 ? "No cases yet. Run the demo set or fetch live listings." : waiting > 0 ? `${waiting} ${waiting === 1 ? "case needs" : "cases need"} your decision.` : running ? "Agents are working." : "Nothing waiting on you."}
            </p>
            {items.length > 0 && <p className="serial mt-1">{source ? `${source} · ` : ""}{items.length - added} fetched{added > 0 ? `, ${added} added from flagged listings` : ""}</p>}
            {m && m.funnel.deliberated > 0 && <p className="serial mt-1">{m.funnel.deliberated} cases reviewed so far, {Math.round(m.latency_ms.case.p50 / 1000)}s and ${m.cost.usd_per_case.toFixed(2)} each</p>}
          </div>
          <section aria-label="Load listings" className="flex flex-wrap items-end gap-x-4 gap-y-3">
            <button onClick={() => run("demo")} disabled={busy || running} className={`${btn} bg-ink text-surface hover:bg-ink-2`}>Run demo set</button>
            <form onSubmit={(e) => { e.preventDefault(); run("live"); }} className="flex flex-wrap items-end gap-3">
              <label className="text-sm text-muted">Fetch live by
                <select value={sweep} onChange={(e) => setSweep(e.target.value)} className="mt-1 block min-h-11 w-52 border border-line bg-surface px-3 text-base text-ink">
                  {SWEEPS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
                  <option value="">Keyword</option>
                </select></label>
              {sweep === "" && <label className="text-sm text-muted">Keyword<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="bone netsuke" className="mt-1 block min-h-11 w-48 border border-line bg-surface px-3 text-base text-ink" /></label>}
              <label className="text-sm text-muted">Max<input type="number" min={1} max={MAX_CAP} value={cap} onChange={(e) => setCap(Math.min(MAX_CAP, Math.max(1, Number(e.target.value) || 1)))} aria-label={`Max items, up to ${MAX_CAP}`} className="mt-1 block min-h-11 w-20 border border-line bg-surface px-3 text-base text-ink" /></label>
              <button type="submit" disabled={busy || running || (sweep === "" && !query.trim())} className={`${btn} border border-ink hover:bg-surface`}>Fetch live</button>
            </form>
          </section>
        </header>
        {problems.length > 0 && <p role="alert" className="border-b border-amber/60 bg-amber-tint px-3 py-2 text-ink">{problems.join(". ")}.</p>}
        {busy && <p role="status" className="border-b border-line py-2 text-muted">Fetching from eBay…</p>}
        {error && <p role="alert" className="border-b border-red/30 bg-red-tint px-3 py-2 text-red">{error}</p>}


        {GROUPS.map((g) => {
          const rows = items.filter(g.test);
          if (rows.length === 0) return null;
          return (
            <section key={g.key} aria-labelledby={`g-${g.key}`} className="mt-8">
              <div className="flex flex-wrap items-baseline gap-x-4 border-b border-ink pb-1.5">
                <h2 id={`g-${g.key}`} className="serif text-xl">{g.title}</h2>
                <span className="serial">{rows.length}</span>
              </div>
              <ul className="-mx-3 divide-y divide-line">{rows.map((i, n) => <li key={i.listing_id} className="rise" style={{ animationDelay: `${Math.min(n, 8) * 40}ms` }}>{Row({ i })}</li>)}</ul>
            </section>
          );
        })}

        <section aria-labelledby="recorded" className="mt-12">
          <h2 id="recorded" className="serif border-b border-ink pb-1.5 text-xl">Recorded reviews</h2>
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
          <h2 id="all" className="serif border-b border-ink pb-1.5 text-xl">All listings{rows ? ` (${rows.length})` : ""}</h2>
          {rows === null ? <p className="mt-6 text-muted">Loading listings…</p>
            : rows.length === 0 ? <p className="mt-6 text-muted">No listings found.</p>
            : <div className="mt-5 grid gap-x-5 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">{rows.slice(0, shown).map((row) => <ListingCard key={row.listing.id} row={row} />)}</div>}
          {rows && rows.length > shown && <button onClick={() => setShown((n) => n + 48)} className="press mt-8 min-h-11 border border-ink px-4 py-2.5 font-semibold hover:bg-surface">Show more ({rows.length - shown} left)</button>}
        </section>
      </div>
    </main>
  );
}

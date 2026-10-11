"use client";
import { useCallback, useEffect, useState } from "react";
import { getMarket, getMetrics, refreshNow } from "@/lib/api";
import type { ListingChange, MarketStats, Metrics } from "@/lib/types";

const ms = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`);
const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`;

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="bg-surface p-4"><dt className="text-sm text-muted">{label}</dt><dd className="display mt-1 text-2xl">{value}</dd>{note && <p className="mono mt-1 text-sm text-muted">{note}</p>}</div>;
}

export default function MetricsPage() {
  const [m, setM] = useState<Metrics | null>(null);
  const [market, setMarket] = useState<MarketStats | null>(null);
  useEffect(() => { getMarket().then(setMarket).catch(() => {}); }, []);
  const [offline, setOffline] = useState(false);
  const [changes, setChanges] = useState<ListingChange[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => getMetrics().then((d) => { setM(d); setOffline(false); }).catch(() => setOffline(true)), []);
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);

  async function refresh() {
    setBusy(true); setNote(null);
    try { setChanges(await refreshNow()); load(); }
    catch { setNote("Refresh is not available yet."); }
    finally { setBusy(false); }
  }

  if (!m) return <main className="shell-grid min-h-[calc(100dvh-3.5rem)]"><p className="mx-auto max-w-5xl px-5 py-8 text-muted">{offline ? "The review service is offline. Start the backend and reload." : "Loading…"}</p></main>;
  const f = m.funnel;
  const steps: [string, number][] = [["Ingested", f.ingested], ["Screened out", f.screened_out], ["Reviewed by agents", f.deliberated], ["Errors", f.errors]];
  const outs: [string, number][] = [["File", f.FILE], ["Contested", f.CONTESTED], ["Watchlist", f.WATCHLIST], ["Dismiss", f.DISMISS]];
  const total = Math.max(f.ingested, 1);
  const pct = (n: number) => `${(n / total) * 100}%`;
  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-5 py-6 sm:px-8">
        <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line pb-3">
          <h1 className="text-xl font-semibold tracking-tight">Metrics</h1>
          <p className="text-sm text-muted">Measured from this server's runs{offline ? " · offline, showing the last reading" : ""}</p>
        </header>

        <section aria-label="Funnel" className="flex flex-col gap-3">
          <h2 className="rule-label">Funnel</h2>
          <div className="flex h-10 w-full overflow-hidden border border-line bg-sunken" role="img" aria-label={`${f.ingested} ingested`}>
            <span className="bg-ink" style={{ width: pct(f.deliberated) }} title="Reviewed by agents" />
            <span className="bg-cobalt/40" style={{ width: pct(f.screened_out) }} title="Screened out" />
          </div>
          <dl className="grid grid-cols-2 gap-px border border-line bg-line [&>*:last-child:nth-child(odd)]:col-span-2 sm:grid-cols-4">
            {[...steps, ...outs.slice(0, 1)].map(([k, v]) => <Stat key={k} label={k} value={String(v)} />)}
            {outs.slice(1).map(([k, v]) => <Stat key={k} label={k} value={String(v)} />)}
          </dl>
        </section>

        <section aria-label="Speed and cost" className="grid gap-6 sm:grid-cols-2">
          <div className="flex flex-col gap-3"><h2 className="rule-label">Speed</h2>
            <dl className="grid grid-cols-2 gap-px border border-line bg-line [&>*:last-child:nth-child(odd)]:col-span-2">
              <Stat label="Listings per minute" value={m.throughput_per_min.toFixed(1)} note="last 10 min" />
              <Stat label="Case, typical" value={ms(m.latency_ms.case.p50)} note={`slowest 1 in 20: ${ms(m.latency_ms.case.p95)}`} />
              <Stat label="Screening, typical" value={ms(m.latency_ms.triage.p50)} note={`slowest 1 in 20: ${ms(m.latency_ms.triage.p95)}`} />
            </dl></div>
          <div className="flex flex-col gap-3"><h2 className="rule-label">Cost</h2>
            <dl className="grid grid-cols-2 gap-px border border-line bg-line [&>*:last-child:nth-child(odd)]:col-span-2">
              <Stat label="Per case" value={usd(m.cost.usd_per_case)} />
              <Stat label="Total" value={usd(m.cost.usd_total)} note={`${m.cost.tokens_in.toLocaleString()} in · ${m.cost.tokens_out.toLocaleString()} out`} />
            </dl>
            <ul className="mono text-sm text-muted">{Object.entries(m.by_model).map(([k, v]) => <li key={k}>{k}: {v.calls} calls · {usd(v.usd)}</li>)}</ul></div>
        </section>

        {market && <section aria-label="Market" className="grid gap-6 sm:grid-cols-3">
          {([["By marketplace", market.by_marketplace], ["By country", market.by_country], ["By material", market.by_material]] as const).map(([title, g]) => (
            <div key={title} className="flex flex-col gap-3"><h2 className="rule-label">{title}</h2>
              <ul className="mono text-sm">{Object.entries(g).sort((a, b) => b[1].count - a[1].count).slice(0, 8).map(([k, v]) => <li key={k} className="flex justify-between gap-3"><span>{k}</span><span className="text-muted">{v.count} · median ${Math.round(v.median_price_usd)}</span></li>)}</ul></div>))}
        </section>}

        <section aria-label="Refresh and strikes" className="grid gap-6 sm:grid-cols-2">
          <div className="flex flex-col gap-3"><h2 className="rule-label">Refresh</h2>
            <p className="text-muted">{m.refresh.last_run_at ? `Last run ${new Date(m.refresh.last_run_at).toLocaleTimeString()}: ${m.refresh.checked} checked, ${m.refresh.changed} changed, ${m.refresh.removed} removed` : "Not run yet"}</p>
            <button onClick={refresh} disabled={busy} className="press min-h-11 w-fit bg-ink px-4 py-2.5 font-semibold text-surface hover:bg-cobalt disabled:opacity-40">{busy ? "Checking…" : "Refresh now"}</button>
            {note && <p role="alert" className="text-red">{note}</p>}
            {changes && (changes.length === 0 ? <p className="text-muted">No changes found.</p> :
              <ul className="mono text-sm">{changes.map((c, i) => <li key={i}>{c.listing_id} · {c.kind.replace("_", " ")}</li>)}</ul>)}</div>
          <div className="flex flex-col gap-3"><h2 className="rule-label">Reports (simulated)</h2>
            <dl className="grid grid-cols-2 gap-px border border-line bg-line [&>*:last-child:nth-child(odd)]:col-span-2">
              <Stat label="Pending review" value={String(m.strikes.pending_review)} />
              <Stat label="Approved" value={String(m.strikes.approved)} />
              <Stat label="Submitted" value={String(m.strikes.submitted_simulated)} />
              <Stat label="Listing removed" value={String(m.strikes.observed_removed)} />
            </dl></div>
        </section>
      </div>
    </main>
  );
}

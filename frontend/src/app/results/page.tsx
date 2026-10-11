"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RatioPlot, type SignalData } from "@/components/RatioPlot";
import { getMarket, getMetrics, refreshNow } from "@/lib/api";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalCondition, EvalResults, ListingChange, MarketStats, Metrics } from "@/lib/types";

const ms = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`);
const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`;

function Section({ id, title, note, children }: { id: string; title: string; note?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-x-12 gap-y-5 border-t border-ink pt-6 md:grid-cols-[13rem_minmax(0,1fr)]">
      <div>
        <h2 id={id} className="serif text-[1.65rem] leading-tight md:sticky md:top-20">{title}</h2>
        {note && <p className="mt-2 max-w-[13rem] text-sm text-muted">{note}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

/** A ledger row: label, dotted leader, value. */
function Row({ k, v, note }: { k: string; v: string; note?: string }) {
  return (
    <div className="flex items-baseline gap-3 py-1.5">
      <dt>{k}{note && <span className="ml-2 text-sm text-muted">{note}</span>}</dt>
      <span aria-hidden className="min-w-4 flex-1 border-b border-dotted border-line" />
      <dd className="font-semibold">{v}</dd>
    </div>
  );
}

const Big = ({ children }: { children: React.ReactNode }) => <span className="serif whitespace-nowrap text-[1.65rem] font-semibold leading-none text-ink">{children}</span>;

const CONDITIONS: { key: Condition; head: string; sub: string }[] = [
  { key: "A", head: "Listing only", sub: "one reading" },
  { key: "B", head: "One agent", sub: "same evidence" },
  { key: "C", head: "Three agents", sub: "full review" },
];

function Accuracy({ results }: { results: EvalResults | null }) {
  if (!results || results._stub || !results.C) {
    return <p className="max-w-prose text-muted">Not measured yet. This table compares one reading of the listing, one agent with the full evidence, and the three-agent review over the labeled set. It fills in from <span className="mono">results/eval.json</span> when that run exists. We show no placeholder numbers.</p>;
  }
  const outOf = (n: number, of: number) => (of === 0 ? "not tested" : `${n} of ${of}`);
  const rows: { label: string; cell: (v: EvalCondition, k: Condition) => string }[] = [
    { label: "Trafficking listings caught", cell: (v) => outOf(v.caught, v.n_pos) },
    { label: "Honest listings wrongly filed", cell: (v) => outOf(v.false_accusations, v.n_neg) },
    { label: "Caught, or handed to a person", cell: (v, k) => outOf(k === "C" ? v.caught_or_escalated ?? v.caught : v.caught, v.n_pos) },
    { label: "Reading per case, input tokens", cell: (v) => v.avg_input_tokens.toLocaleString() },
    { label: "Claims thrown out per case", cell: (v) => (v.claims_rejected_per_case === undefined ? "n/a" : v.claims_rejected_per_case.toFixed(2)) },
    { label: "Changed mind on new evidence", cell: (v, k) => (k === "C" ? String(v.stance_changes_after_new_evidence ?? 0) : "n/a") },
  ];
  const n = results.C;
  const examples = [...(results.examples?.c_caught_b_missed ?? []), ...(results.examples?.b_false_accusation_c_avoided ?? [])];
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] border-collapse text-left">
          <caption className="sr-only">Accuracy by review setup</caption>
          <thead>
            <tr>
              <th scope="col" className="w-[34%] pb-3" />
              {CONDITIONS.map((c) => (
                <th key={c.key} scope="col" className={`px-2 sm:px-4 pb-3 align-bottom font-normal ${c.key === "C" ? "bg-ink text-surface" : ""}`}>
                  <span className="serif block text-lg font-semibold leading-tight">{c.head}</span>
                  <span className={`text-sm ${c.key === "C" ? "text-surface/70" : "text-muted"}`}>{c.sub}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-line">
                <th scope="row" className="py-3 pr-4 font-normal">{r.label}</th>
                {CONDITIONS.map((c) => {
                  const v = results[c.key];
                  return <td key={c.key} className={`px-2 sm:px-4 py-3 font-semibold ${c.key === "C" ? "bg-cobalt-tint" : ""}`}>{v ? r.cell(v, c.key) : "n/a"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-prose text-sm text-muted">Measured on {n.n_pos} trafficking and {n.n_neg} honest listings per setup. At this size a single case moves a number a lot; read the pattern, not the decimals.</p>
      {examples.length > 0 && <p className="mt-4 text-sm">Worth reading: {examples.map((id, i) => <span key={id}>{i > 0 && ", "}<Link href={`/listing/${id}`} className="font-semibold text-cobalt-ink underline underline-offset-4">{id}</Link></span>)}</p>}
    </>
  );
}

const SEGMENTS: { key: keyof Metrics["funnel"]; label: string; color: string }[] = [
  { key: "screened_out", label: "Screened out", color: "bg-line" },
  { key: "DISMISS", label: "Dismissed", color: "bg-green" },
  { key: "WATCHLIST", label: "Watchlist", color: "bg-cobalt" },
  { key: "CONTESTED", label: "Contested", color: "bg-amber" },
  { key: "FILE", label: "File", color: "bg-red" },
  { key: "errors", label: "Errors", color: "bg-ink" },
];

function Funnel({ f }: { f: Metrics["funnel"] }) {
  if (f.ingested === 0) return <p className="text-muted">No runs yet. Start a batch on the <Link href="/" className="font-semibold text-cobalt-ink underline underline-offset-4">Cases</Link> page and the funnel fills in.</p>;
  return (
    <>
      <p className="max-w-prose"><Big>{f.ingested}</Big> listings came in. <Big>{f.deliberated}</Big> got a full three-agent review; the rest were screened out first.</p>
      <div className="mt-4 flex h-6 w-full gap-px overflow-hidden bg-surface" role="img" aria-label={SEGMENTS.map((s) => `${s.label} ${f[s.key]}`).join(", ")}>
        {SEGMENTS.map((s) => f[s.key] > 0 && <span key={s.key} className={s.color} style={{ width: `${(f[s.key] / f.ingested) * 100}%` }} />)}
        <span className="flex-1 bg-sunken" />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-8 sm:grid-cols-3">
        {SEGMENTS.map((s) => <div key={s.key} className="flex items-center gap-2 py-1"><i className={`size-2.5 shrink-0 ${s.color}`} /><dt className="text-muted">{s.label}</dt><dd className="ml-auto font-semibold">{f[s.key]}</dd></div>)}
        <div className="flex items-center gap-2 py-1"><i className="size-2.5 shrink-0 bg-sunken" /><dt className="text-muted">Not finished</dt><dd className="ml-auto font-semibold">{Math.max(0, f.ingested - SEGMENTS.reduce((n, s) => n + f[s.key], 0))}</dd></div>
      </dl>
    </>
  );
}

function Operations() {
  const [m, setM] = useState<Metrics | null>(null);
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [offline, setOffline] = useState(false);
  const [changes, setChanges] = useState<ListingChange[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => getMetrics().then((d) => { setM(d); setOffline(false); }).catch(() => setOffline(true)), []);
  useEffect(() => { getMarket().then(setMarket).catch(() => {}); }, []);
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);

  async function refresh() {
    setBusy(true); setNote(null);
    try { setChanges(await refreshNow()); load(); }
    catch { setNote("Refresh is not available yet."); }
    finally { setBusy(false); }
  }

  if (!m) return <p className="text-muted">{offline ? "The review service is offline. Start the backend and reload." : "Loading…"}</p>;
  return (
    <div className="flex flex-col gap-10">
      {offline && <p role="status" className="text-amber-ink">Backend offline. Showing the last reading.</p>}
      <Funnel f={m.funnel} />
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        <div>
          <h3 className="serif mb-1 text-xl">Speed</h3>
          <dl>
            <Row k="Listings per minute" v={m.throughput_per_min.toFixed(1)} note="last 10 min" />
            <Row k="A case, typically" v={ms(m.latency_ms.case.p50)} />
            <Row k="A case, slowest 1 in 20" v={ms(m.latency_ms.case.p95)} />
            <Row k="Screening, typically" v={ms(m.latency_ms.triage.p50)} />
          </dl>
        </div>
        <div>
          <h3 className="serif mb-1 text-xl">Cost</h3>
          <dl>
            <Row k="Per case" v={usd(m.cost.usd_per_case)} />
            <Row k="Total" v={usd(m.cost.usd_total)} />
            <Row k="Tokens in / out" v={`${m.cost.tokens_in.toLocaleString()} / ${m.cost.tokens_out.toLocaleString()}`} />
            {Object.entries(m.by_model).map(([k, v]) => <Row key={k} k={k} v={`${v.calls} calls · ${usd(v.usd)}`} />)}
          </dl>
        </div>
      </div>
      {market && (
        <div className="grid gap-x-12 gap-y-8 lg:grid-cols-3">
          {([["By marketplace", market.by_marketplace], ["By country", market.by_country], ["By material", market.by_material]] as const).map(([title, g]) => (
            <div key={title}>
              <h3 className="serif mb-1 text-xl">{title}</h3>
              <dl>{Object.entries(g).sort((a, b) => b[1].count - a[1].count).slice(0, 6).map(([k, v]) => <Row key={k} k={k} v={String(v.count)} note={`median $${Math.round(v.median_price_usd)}`} />)}</dl>
            </div>
          ))}
        </div>
      )}
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        <div>
          <h3 className="serif mb-1 text-xl">Listings changing under us</h3>
          <p className="text-muted">{m.refresh.last_run_at ? `Last check ${new Date(m.refresh.last_run_at).toLocaleTimeString()}: ${m.refresh.checked} checked, ${m.refresh.changed} changed, ${m.refresh.removed} removed.` : "Not checked yet."}</p>
          <button onClick={refresh} disabled={busy} className="press mt-3 min-h-11 bg-ink px-4 py-2.5 font-semibold text-surface hover:bg-cobalt disabled:opacity-40">{busy ? "Checking…" : "Check for changes"}</button>
          {note && <p role="alert" className="mt-2 text-red">{note}</p>}
          {changes && (changes.length === 0 ? <p className="mt-2 text-muted">No changes found.</p> : <ul className="mt-2">{changes.map((c, i) => <li key={i}>{c.listing_id} · {c.kind.replace("_", " ")}</li>)}</ul>)}
        </div>
        <div>
          <h3 className="serif mb-1 text-xl">Takedown reports <span className="text-base font-normal text-muted">(simulated)</span></h3>
          <dl>
            <Row k="Waiting for a person" v={String(m.strikes.pending_review)} />
            <Row k="Approved" v={String(m.strikes.approved)} />
            <Row k="Submitted" v={String(m.strikes.submitted_simulated)} />
            <Row k="Listing then removed" v={String(m.strikes.observed_removed)} />
          </dl>
        </div>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [signals, setSignals] = useState<SignalData | null>(null);
  useEffect(() => {
    loadEval().then(({ data }) => setResults(data)).catch(() => setResults(null));
    fetch("/stub/signals.json").then((r) => (r.ok ? r.json() : null)).then(setSignals).catch(() => setSignals(null));
  }, []);
  const p = signals?.price, l = signals?.links, d = signals?.dataset;
  return (
    <main className="min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto flex max-w-5xl flex-col gap-14 px-5 pb-20 pt-10 sm:px-8">
        <header className="max-w-2xl">
          <h1 className="serif text-5xl font-semibold leading-[1.02] text-balance">How well it works</h1>
          <p className="mt-4 text-base text-muted">Every number below is computed from our dataset or measured from real runs. Anything we have not run says so.</p>
        </header>

        <Section id="accuracy" title="Does disagreement help?" note="Same listings, three ways of reviewing them.">
          <Accuracy results={results} />
        </Section>

        <Section id="price" title="Price helps, but not alone" note="Measured by code. No model involved.">
          {p && d ? <>
            <p className="max-w-prose"><Big>{p.planted_flagged} of {p.planted_total}</Big> reconstructed cases are priced at {p.flag_at}x the usual or more. So are <Big>{p.real_flagged} of {p.real_total}</Big> real listings. A price-only rule would file all of them; the Defender and the photo examiner exist to close that gap.</p>
            <div className="mt-6"><RatioPlot price={p} /></div>
            <p className="mt-3 max-w-prose text-sm text-muted">We set the reconstructed prices to match the documented pattern, so the first number confirms the dataset rather than proving the method.</p>
          </> : <p className="text-muted">Loading measurements…</p>}
        </Section>

        <Section id="links" title="Wording and photos expose networks" note="Measured by code. No model involved.">
          {l ? <p className="max-w-prose"><Big>{l.network_linked} of {l.network_total}</Big> listings in the designed three-seller network link to the other sellers, through two long shared phrases or a reused photo. Only <Big>{l.real_linked} of {l.real_total}</Big> real listings link to another seller the same way. The first version of the rule matched over a third of them, because ordinary shipping boilerplate counted.</p> : <p className="text-muted">Loading measurements…</p>}
        </Section>

        <Section id="ops" title="Running it" note="Measured from this server's runs.">
          <Operations />
        </Section>

        <footer className="border-t border-line pt-5 text-sm text-muted">
          <p className="max-w-prose">Trafficking listings come down quickly, so the {d?.planted_cases ?? ""} positive cases are reconstructed from documented ones and marked as such. The {d?.real_listings ?? ""} real listings are assumed lawful; a few may not be. Sellers appear under pseudonyms.</p>
        </footer>
      </div>
    </main>
  );
}

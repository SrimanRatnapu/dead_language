"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { RatioPlot, type SignalData } from "@/components/RatioPlot";
import { getMetrics } from "@/lib/api";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalResults, Metrics } from "@/lib/types";

const secs = (ms: number) => `${(ms / 1000).toFixed(0)} s`;
const usd = (n: number) => `$${n.toFixed(2)}`;

const SETUPS: { key: Condition; head: string }[] = [
  { key: "A", head: "Listing only" },
  { key: "B", head: "One agent" },
  { key: "C", head: "Three agents" },
];

function Accuracy({ r }: { r: EvalResults | null }) {
  if (!r?.C || r._stub) return <p className="text-muted">Not measured yet.</p>;
  const of = (n: number, total: number) => (total === 0 ? "n/a" : `${n} of ${total}`);
  const rows: [string, (c: Condition) => string][] = [
    ["Trafficking listings caught", (k) => of(r[k]!.caught, r[k]!.n_pos)],
    ["Honest listings wrongly filed", (k) => of(r[k]!.false_accusations, r[k]!.n_neg)],
    ["Caught or sent to a person", (k) => of(k === "C" ? r.C!.caught_or_escalated ?? r.C!.caught : r[k]!.caught, r[k]!.n_pos)],
  ];
  return (
    <table className="w-full max-w-2xl border-collapse text-left">
      <thead><tr><th className="w-[40%] pb-2" />{SETUPS.map((s) => <th key={s.key} className={`px-3 pb-2 font-semibold ${s.key === "C" ? "bg-cobalt-tint" : ""}`}>{s.head}</th>)}</tr></thead>
      <tbody>{rows.map(([label, f]) => (
        <tr key={label} className="border-t border-line">
          <th scope="row" className="py-2 pr-3 font-normal">{label}</th>
          {SETUPS.map((s) => <td key={s.key} className={`px-3 py-2 ${s.key === "C" ? "bg-cobalt-tint font-semibold" : ""}`}>{r[s.key] ? f(s.key) : "n/a"}</td>)}
        </tr>))}
      </tbody>
    </table>
  );
}

const SEGMENTS: { key: keyof Metrics["funnel"]; label: string; color: string }[] = [
  { key: "DISMISS", label: "Dismissed", color: "bg-green" },
  { key: "WATCHLIST", label: "Watchlist", color: "bg-cobalt" },
  { key: "CONTESTED", label: "Contested", color: "bg-amber" },
  { key: "FILE", label: "File", color: "bg-red" },
  { key: "errors", label: "Errors", color: "bg-ink" },
];

function Runs() {
  const [m, setM] = useState<Metrics | null>(null);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const load = () => getMetrics().then((d) => { setM(d); setOffline(false); }).catch(() => setOffline(true));
    load(); const t = setInterval(load, 5000); return () => clearInterval(t);
  }, []);
  if (!m) return <p className="text-muted">{offline ? "The review service is offline." : "Loading…"}</p>;
  const f = m.funnel;
  if (f.ingested === 0) return <p className="text-muted">No runs yet. Start a batch on the <Link href="/" className="font-semibold text-cobalt-ink underline underline-offset-4">Cases</Link> page.</p>;
  return (
    <>
      <p><span className="serif text-3xl font-semibold">{f.ingested}</span> listings reviewed, at <b>{secs(m.latency_ms.case.p50)}</b> and <b>{usd(m.cost.usd_per_case)}</b> per case.</p>
      <div className="mt-3 flex h-5 w-full max-w-2xl gap-px overflow-hidden bg-sunken" role="img" aria-label={SEGMENTS.map((s) => `${s.label} ${f[s.key]}`).join(", ")}>
        {SEGMENTS.map((s) => f[s.key] > 0 && <span key={s.key} className={s.color} style={{ width: `${(f[s.key] / f.ingested) * 100}%` }} />)}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
        {SEGMENTS.map((s) => <li key={s.key} className="flex items-center gap-1.5"><i className={`size-2.5 ${s.color}`} />{s.label} <b className="text-ink">{f[s.key]}</b></li>)}
      </ul>
    </>
  );
}

function Signals() {
  const [d, setD] = useState<SignalData | null>(null);
  useEffect(() => { fetch("/stub/signals.json").then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => setD(null)); }, []);
  if (!d) return <p className="text-muted">Loading…</p>;
  const { price: p, links: l } = d;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="font-semibold">Price alone is not enough</h3>
        <p className="mb-3 text-muted">Each dot is a listing, plotted by its price against the median for the same stated material. {p.planted_flagged} of {p.planted_total} reconstructed trafficking cases sit at {p.flag_at}× or more, but so do {p.real_flagged} of {p.real_total} real listings. A price-only rule would file all of them, so the other agents exist to separate them.</p>
        <RatioPlot price={p} />
      </div>
      <div>
        <h3 className="font-semibold">Shared wording and photos link sellers</h3>
        <p className="text-muted">All {l.network_linked} of {l.network_total} listings in the designed network link to the other sellers. Only {l.real_linked} of {l.real_total} real listings link to another seller this way, so a hit means something.</p>
      </div>
    </div>
  );
}

function Section({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return <section className="border-t border-ink pt-4"><h2 className="serif text-2xl">{title}</h2><p className="mb-4 text-sm text-muted">{sub}</p>{children}</section>;
}

export default function ResultsPage() {
  const [results, setResults] = useState<EvalResults | null>(null);
  useEffect(() => { loadEval().then(({ data }) => setResults(data)).catch(() => setResults(null)); }, []);
  return (
    <main className="min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto flex max-w-3xl flex-col gap-8 px-5 pb-16 pt-8 sm:px-8">
        <header>
          <h1 className="serif text-4xl font-semibold">Results</h1>
          <p className="mt-2 text-muted">Two questions: is the three-agent review more accurate than simpler setups, and what has this server actually run?</p>
        </header>
        <Section title="Accuracy" sub="Same labeled listings, three ways of reviewing them. Positive cases are reconstructed, so read the pattern, not the decimals."><Accuracy r={results} /></Section>
        <Section title="Signals" sub="What the helpers compute from the listings, with no model involved."><Signals /></Section>
        <Section title="Runs on this server" sub="Measured live from every case run here."><Runs /></Section>
      </div>
    </main>
  );
}

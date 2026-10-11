"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { RatioPlot, type SignalData } from "@/components/RatioPlot";
import { getMetrics } from "@/lib/api";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalResults, Metrics } from "@/lib/types";

const SETUPS: { key: Condition; name: string; note: string }[] = [
  { key: "A", name: "Listing text only", note: "no evidence, no debate" },
  { key: "B", name: "One agent", note: "evidence, no debate" },
  { key: "C", name: "Three agents", note: "evidence and debate" },
];

/** One square per listing: filled when the setup got it right. Reads at any n without a chart library. */
function Squares({ right, total, color }: { right: number; total: number; color: string }) {
  return (
    <span className="flex flex-wrap gap-1" role="img" aria-label={`${right} of ${total}`}>
      {Array.from({ length: total }, (_, i) => <i key={i} className={`size-3.5 ${i < right ? color : "bg-sunken"}`} />)}
    </span>
  );
}

function Accuracy({ r }: { r: EvalResults | null }) {
  if (!r?.C || r._stub) return <p className="text-muted">Not measured yet.</p>;
  const honest = r.C.n_neg;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="mb-3 font-semibold">Trafficking listings caught</p>
        <ul className="flex flex-col gap-3">
          {SETUPS.map((s) => r[s.key] && (
            <li key={s.key} className="grid grid-cols-[11rem_1fr_auto] items-center gap-4">
              <span><b className={s.key === "C" ? "text-cobalt-ink" : ""}>{s.name}</b><br /><span className="text-sm text-muted">{s.note}</span></span>
              <Squares right={r[s.key]!.caught} total={r[s.key]!.n_pos} color={s.key === "C" ? "bg-cobalt" : "bg-ink"} />
              <span className="mono">{r[s.key]!.caught}/{r[s.key]!.n_pos}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-muted">
        {honest === 0
          ? "Honest listings wrongly filed: not measured yet. This run had no honest listings, so it can say what each setup catches but not what it gets wrong."
          : `Honest listings wrongly filed, out of ${honest}: ${SETUPS.map((s) => `${s.name.toLowerCase()} ${r[s.key]?.false_accusations ?? "n/a"}`).join(", ")}.`}
      </p>
    </div>
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
  if (f.ingested === 0) return <p className="text-muted">No runs yet. Start a batch on the <Link href="/desk" className="font-semibold text-cobalt-ink underline underline-offset-4">Review desk</Link> page.</p>;
  return (
    <div>
      <div className="flex h-6 w-full gap-px overflow-hidden bg-sunken" role="img" aria-label={SEGMENTS.map((s) => `${s.label} ${f[s.key]}`).join(", ")}>
        {SEGMENTS.map((s) => f[s.key] > 0 && <span key={s.key} className={s.color} style={{ width: `${(f[s.key] / f.ingested) * 100}%` }} />)}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
        {SEGMENTS.map((s) => <li key={s.key} className="flex items-center gap-1.5"><i className={`size-2.5 ${s.color}`} />{s.label} <b className="text-ink">{f[s.key]}</b></li>)}
      </ul>
      <p className="mt-4 text-muted">
        Median {(m.latency_ms.case.p50 / 1000).toFixed(0)} s per case, {m.throughput_per_min.toFixed(1)} cases a minute, ${m.cost.usd_per_case.toFixed(2)} each.
      </p>
    </div>
  );
}

/** A finding: the claim as a sentence on the left, its evidence on the right. */
function Finding({ claim, children }: { claim: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="grid gap-x-12 gap-y-5 border-t border-ink pt-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div>
        <h2 className="serif text-[1.7rem] font-semibold leading-tight [text-wrap:balance]">{claim}</h2>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export default function ResultsPage() {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [sig, setSig] = useState<SignalData | null>(null);
  useEffect(() => {
    loadEval().then(({ data }) => setResults(data)).catch(() => setResults(null));
    fetch("/stub/signals.json").then((r) => (r.ok ? r.json() : null)).then(setSig).catch(() => setSig(null));
  }, []);
  const p = sig?.price, l = sig?.links;
  return (
    <main className="min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto flex max-w-5xl flex-col gap-12 px-5 pb-20 pt-10 sm:px-8">
        <h1 className="serif max-w-3xl text-4xl font-extrabold leading-tight [text-wrap:balance]">
          A price can flag a listing. Only the debate tells you whether to act on it.
        </h1>

        <Finding claim="Which way of reviewing catches the most trafficking listings?">
          <Accuracy r={results} />
        </Finding>

        {p && (
          <Finding claim={<>A price-only rule would file {p.real_flagged} real listings alongside the {p.planted_flagged} trafficking cases.</>}>
            <p className="mb-3 text-muted">Each dot is a listing, plotted by its price against the median for the same stated material. {p.planted_flagged} of {p.planted_total} trafficking cases sit at {p.flag_at}× or more. So do {p.real_flagged} of {p.real_total} real listings.</p>
            <RatioPlot price={p} />
          </Finding>
        )}

        {l && (
          <Finding claim="Shared wording and photos link sellers, and almost never by accident.">
            <p className="text-muted">All {l.network_linked} of {l.network_total} listings in the designed network link to the other sellers. Only {l.real_linked} of {l.real_total} real listings link to another seller this way, so a hit means something.</p>
          </Finding>
        )}

        <Finding claim="What a real run looked like: outcomes, speed and cost.">
          <Runs />
        </Finding>
      </div>
    </main>
  );
}

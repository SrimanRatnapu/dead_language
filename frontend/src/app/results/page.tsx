"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Signals, type SignalData } from "@/components/Signals";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalResults } from "@/lib/types";

const COLUMNS: { key: Condition; title: string; detail: string }[] = [{ key: "A", title: "Listing only", detail: "One reading" }, { key: "B", title: "One agent", detail: "Same evidence" }, { key: "C", title: "Three agents", detail: "Buyer · Defender · Caseload" }];

function AgentComparison({ results }: { results: EvalResults | null }) {
  if (!results || results._stub || !results.C) {
    return <div className="mt-6 border border-dashed border-line bg-surface/60 p-6"><p className="display text-3xl">Not measured yet.</p><p className="mt-2 max-w-2xl text-muted">This comparison needs model runs over the evaluation set: one reading of the listing, one agent with the full evidence, and the three-agent review. The page fills in from <span className="mono">results/eval.json</span> as soon as that run exists. We show no placeholder numbers.</p></div>;
  }
  return <>
    <div className="mt-6 grid gap-px border border-line bg-line md:grid-cols-3">{COLUMNS.map(({ key, title, detail }) => { const value = results[key]; if (!value) return null; return <div key={key} className={`bg-surface p-5 ${key === "C" ? "bg-cobalt-tint" : ""}`}><p className="rule-label mb-4">{detail}</p><h3 className="text-xl font-semibold tracking-tight">{title}</h3><dl className="mt-8 grid grid-cols-2 gap-x-4 gap-y-6"><div><dt className="text-muted">Caught</dt><dd className="display mt-1 text-4xl text-cobalt-ink">{value.caught}</dd></div><div><dt className="text-muted">Wrongly filed</dt><dd className="display mt-1 text-4xl">{value.false_accusations}</dd></div><div><dt className="text-muted">Input tokens</dt><dd className="mt-1 text-lg font-semibold">{value.avg_input_tokens.toLocaleString()}</dd></div><div><dt className="text-muted">Output tokens</dt><dd className="mt-1 text-lg font-semibold">{value.avg_output_tokens.toLocaleString()}</dd></div></dl></div>; })}</div>
    {results.examples && (results.examples.c_caught_b_missed.length > 0 || results.examples.b_false_accusation_c_avoided.length > 0) && <div className="mt-6"><h3 className="rule-label mb-3">Cases worth reading</h3><div className="flex flex-wrap gap-2">{[...results.examples.c_caught_b_missed, ...results.examples.b_false_accusation_c_avoided].map((listingId) => <Link key={listingId} href={`/?listing=${listingId}`} className="press border border-line bg-surface px-3 py-2 hover:border-cobalt hover:text-cobalt-ink">{listingId}</Link>)}</div></div>}
  </>;
}

export default function ResultsPage() {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [signals, setSignals] = useState<SignalData | null>(null);
  useEffect(() => {
    loadEval().then(({ data }) => setResults(data)).catch(() => setResults(null));
    fetch("/stub/signals.json").then((r) => (r.ok ? r.json() : null)).then(setSignals).catch(() => setSignals(null));
  }, []);
  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <header className="max-w-3xl border-b border-line pb-9">
          <p className="rule-label mb-4 text-cobalt-ink">Evaluation</p>
          <h1 className="display text-5xl sm:text-6xl">What we measured, and what we have not.</h1>
          <p className="mt-4 text-lg text-muted">Every number on this page is computed from our dataset. Where a run has not happened yet, the page says so.</p>
        </header>
        {signals ? <Signals data={signals} /> : <p className="mt-8 text-muted">Loading measurements…</p>}
        <section aria-labelledby="agents" className="mt-12 border-t border-line pt-8">
          <p className="rule-label mb-3 text-cobalt-ink">Needs model runs</p>
          <h2 id="agents" className="display max-w-3xl text-4xl">Does disagreement help?</h2>
          <AgentComparison results={results} />
        </section>
        <p className="mt-12 border-t border-line pt-5 text-sm text-muted">Trafficking listings are taken down quickly, so the {signals?.dataset.planted_cases ?? ""} positive cases are reconstructed from documented ones and marked as such. Real listings are assumed lawful; a few may not be.</p>
      </div>
    </main>
  );
}

"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalCondition, EvalResults } from "@/lib/types";

const COLUMNS: { key: Condition; title: string; sub: string }[] = [
  { key: "listing_only", title: "Listing only", sub: "Reads the listing text and nothing else" },
  { key: "single_agent", title: "One agent with evidence", sub: "One reviewer, same evidence" },
  { key: "three_agent", title: "Three-agent review", sub: "Buyer, Defender and Caseload" },
];

const ROWS: { key: keyof EvalCondition; label: string }[] = [
  { key: "caught", label: "Caught" },
  { key: "wrongly_flagged", label: "Wrongly flagged" },
  { key: "sent_to_human", label: "Sent to a person to decide" },
  { key: "tokens_per_case", label: "Tokens per case" },
  { key: "claims_rejected", label: "Claims rejected" },
];

export default function ResultsPage() {
  const [res, setRes] = useState<EvalResults | null>(null);
  const [offline, setOffline] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadEval().then(({ data, offline: off }) => { setRes(data); setOffline(off); }).catch(() => setFailed(true));
  }, []);

  if (failed) return <p className="p-5 text-red">Results could not be loaded.</p>;
  if (!res) return <p className="p-5 text-muted">Loading results…</p>;

  const pending = !!res._stub;
  const show = (v: number | null) => (pending || v === null ? "—" : v.toLocaleString("en-US"));

  return (
    <div className="mx-auto flex h-[calc(100dvh-3rem)] max-w-5xl flex-col gap-6 overflow-y-auto p-6">
      {pending && <p className="rounded-md bg-sunken px-3 py-2 text-muted">Results are not available yet. The layout below fills in from <span className="mono">results/eval.json</span>.</p>}
      {offline && !pending && <p className="text-muted">Backend offline — showing a saved copy.</p>}

      <div>
        <h1 className="display text-3xl">Does a disagreement help?</h1>
        <p className="mt-1 max-w-[65ch] text-muted">
          {res.n_cases} cases: {res.n_should_flag} that should be flagged and {res.n_should_clear} that should be cleared.
          Trafficking cases are reconstructed from documented ones; the cleared cases are real listings.
        </p>
      </div>

      <table className="w-full border-collapse text-left">
        <thead>
          <tr>
            <th className="w-56" />
            {COLUMNS.map((c) => (
              <th key={c.key} className="pb-3 align-bottom font-normal">
                <span className="block text-base font-semibold">{c.title}</span>
                <span className="block text-muted">{c.sub}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.key} className="border-t border-line">
              <th scope="row" className="py-3 pr-4 font-medium">{r.label}</th>
              {COLUMNS.map((c) => (
                <td key={c.key} className={`py-3 text-2xl tracking-tight ${c.key === "three_agent" ? "font-semibold" : ""}`}>
                  {show(res.conditions[c.key][r.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {res.examiner && !pending && (
        <p>Material examiner accuracy: {res.examiner.correct} of {res.examiner.n} photos read correctly ({Math.round(res.examiner.accuracy * 100)}%).</p>
      )}

      {res.example_cases.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="display text-xl">Example cases</h2>
          <ul className="flex flex-wrap gap-2">
            {res.example_cases.map((c) => (
              <li key={c.replay}><Link href={`/replay/${c.replay}`} className="press block rounded-md border border-line bg-surface px-3 py-1.5 hover:border-ink">{c.label}</Link></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

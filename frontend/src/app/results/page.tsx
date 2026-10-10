"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { loadEval } from "@/lib/stubs";
import type { Condition, EvalResults } from "@/lib/types";

const COLUMNS: { key: Condition; title: string; detail: string }[] = [
  { key: "A", title: "Listing only", detail: "One reading" },
  { key: "B", title: "One agent", detail: "Same evidence" },
  { key: "C", title: "Three agents", detail: "Buyer · Defender · Caseload" },
];

export default function ResultsPage() {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadEval().then(({ data }) => setResults(data)).catch(() => setFailed(true));
  }, []);

  if (failed) return <p className="p-6 text-red">Results could not be loaded.</p>;
  if (!results) return <p className="p-6 text-muted">Loading results…</p>;
  if (results._stub || !results.C) {
    return (
      <main className="mx-auto flex h-[calc(100dvh-3rem)] max-w-5xl items-center px-8">
        <div>
          <h1 className="display text-4xl">Results</h1>
          <p className="mt-2 text-muted">The evaluation has not run yet.</p>
          <Link href="/" className="press mt-6 inline-block rounded-full border border-line px-4 py-2 font-medium hover:border-ink">Back to listings</Link>
        </div>
      </main>
    );
  }

  const n = results.C.n_pos + results.C.n_neg;
  return (
    <main className="mx-auto flex h-[calc(100dvh-3rem)] max-w-5xl flex-col gap-8 overflow-y-auto px-8 py-10">
      <div>
        <h1 className="display text-4xl">Does disagreement help?</h1>
        <p className="mt-2 text-muted">{n} listings evaluated.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {COLUMNS.map(({ key, title, detail }) => {
          const value = results[key];
          if (!value) return null;
          return (
            <section key={key} className={`rounded-2xl border border-line p-5 ${key === "C" ? "bg-surface shadow-[var(--shadow)]" : ""}`}>
              <h2 className="font-semibold">{title}</h2>
              <p className="mb-7 text-muted">{detail}</p>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-5">
                <div><dt className="text-muted">Caught</dt><dd className="display text-4xl">{value.caught}</dd></div>
                <div><dt className="text-muted">Wrongly filed</dt><dd className="display text-4xl">{value.false_accusations}</dd></div>
                <div><dt className="text-muted">Input tokens</dt><dd className="text-xl font-semibold">{value.avg_input_tokens.toLocaleString()}</dd></div>
                <div><dt className="text-muted">Output tokens</dt><dd className="text-xl font-semibold">{value.avg_output_tokens.toLocaleString()}</dd></div>
              </dl>
            </section>
          );
        })}
      </div>

      {results.examples && (results.examples.c_caught_b_missed.length > 0 || results.examples.b_false_accusation_c_avoided.length > 0) && (
        <section className="flex flex-col gap-3">
          <h2 className="display text-2xl">Examples</h2>
          <div className="flex flex-wrap gap-2">
            {[...results.examples.c_caught_b_missed, ...results.examples.b_false_accusation_c_avoided].map((listingId) => (
              <Link key={listingId} href={`/?listing=${listingId}`} className="press rounded-full border border-line px-3 py-1.5 hover:border-ink">{listingId}</Link>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useCaseEvents, type CaseSource, type Speed } from "@/lib/useCaseEvents";
import { Balance } from "./Balance";
import { CaseFileDrawer } from "./CaseFileDrawer";
import { Debate } from "./Debate";
import { DecodedListing } from "./DecodedListing";
import { DemoControls } from "./DemoControls";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { Outcome } from "./Outcome";
import { ProcessLog } from "./ProcessLog";

export type CaseTarget = { kind: "live"; caseId: string } | { kind: "replay"; name: string } | { kind: "fixture" };

export function CaseView({ target }: { target: CaseTarget }) {
  const [speed, setSpeed] = useState<Speed>(1);
  const source = useMemo<CaseSource>(() => (target.kind === "live" ? target : { ...target, speed }), [target, speed]);
  const events = useCaseEvents(source);
  const { state } = events;
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [caseFileOpen, setCaseFileOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  // scripts/record_scripted_demo.py stamps its runs with a "DEMO-" case id; recorded live runs are "C-0001".
  const scripted = Object.values(state.evidence)[0]?.case_id.startsWith("DEMO-") ?? false;

  return (
    <main className="shell-grid flex min-h-[calc(100dvh-3.5rem)] flex-col">
      {events.error && <p className="shrink-0 border-b border-red/30 bg-red-tint px-6 py-2 text-red">{events.error} <Link href="/" className="underline underline-offset-2">Back to cases</Link></p>}
      <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 flex-col px-4 py-4 sm:px-6 lg:px-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3"><Link href="/" className="press -ml-2 inline-flex min-h-11 items-center px-2 text-sm text-muted hover:text-cobalt-ink lg:min-h-0">← All cases</Link><div className="flex flex-wrap items-center gap-2"><button onClick={() => setLogOpen(true)} className="press inline-flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm hover:border-ink lg:min-h-0 lg:py-1.5">Process log<span className="mono text-muted">{state.feed.length}</span></button><DemoControls listingId={state.listing?.id ?? null} events={events} speed={speed} onSpeed={setSpeed} /></div></div>
        {scripted && <p className="mb-3 border-l-2 border-amber bg-amber-tint px-3 py-2 text-sm text-amber-ink"><span className="font-semibold">Scripted walkthrough.</span> The evidence, claim checks and outcome rule ran for real on our dataset. The agents&apos; wording and the photo readings are written by hand until a live run is recorded.</p>}
        <div className="grid min-h-0 flex-1 border border-line bg-bg/70 lg:grid-cols-[minmax(330px,31%)_minmax(0,1fr)]">
          <aside aria-label="Listing under review" className="order-2 overflow-y-auto border-t border-line bg-surface/70 lg:order-1 lg:min-h-0 lg:border-t-0 lg:border-r"><DecodedListing state={state} onOpenEvidence={setOpenEvidence} /></aside>
          <section aria-label="Case review" className="order-1 flex flex-col lg:order-2 lg:min-h-0"><div className="shrink-0 border-b border-line bg-surface/40"><Balance rounds={state.rounds} /></div><div className="lg:min-h-0 lg:flex-1"><Debate state={state} onOpen={setOpenEvidence} /></div><Outcome state={state} onOpenCaseFile={() => setCaseFileOpen(true)} /></section>
        </div>
      </div>
      <EvidenceDrawer evidence={openEvidence ? state.evidence[openEvidence] ?? null : null} listing={state.listing} onClose={() => setOpenEvidence(null)} />
      <ProcessLog state={state} open={logOpen} onClose={() => setLogOpen(false)} />
      <CaseFileDrawer caseFile={state.caseFile} evidence={state.evidence} open={caseFileOpen} onClose={() => setCaseFileOpen(false)} onOpenEvidence={setOpenEvidence} />
    </main>
  );
}

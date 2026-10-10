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

export type CaseTarget = { kind: "live"; caseId: string } | { kind: "replay"; name: string } | { kind: "fixture" };

export function CaseView({ target }: { target: CaseTarget }) {
  const [speed, setSpeed] = useState<Speed>(1);
  const source = useMemo<CaseSource>(() => (target.kind === "live" ? target : { ...target, speed }), [target, speed]);
  const events = useCaseEvents(source);
  const { state } = events;
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [caseFileOpen, setCaseFileOpen] = useState(false);

  return (
    <div className="shell-grid flex min-h-[calc(100dvh-3.5rem)] flex-col">
      {events.error && <p className="shrink-0 border-b border-red/30 bg-red-tint px-6 py-2 text-red">{events.error} <Link href="/" className="underline underline-offset-2">Back to cases</Link></p>}
      <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 flex-col px-4 py-4 sm:px-6 lg:px-8">
        <div className="mb-3 flex justify-end border-b border-line pb-3"><Link href="/" className="press text-sm text-muted hover:text-cobalt-ink">← All cases</Link></div>
        <div className="grid min-h-0 flex-1 border border-line bg-bg/70 lg:grid-cols-[minmax(330px,31%)_minmax(0,1fr)]">
          <aside className="min-h-[440px] overflow-y-auto border-b border-line bg-surface/70 lg:min-h-0 lg:border-b-0 lg:border-r"><DecodedListing state={state} onOpenEvidence={setOpenEvidence} /></aside>
          <section className="flex min-h-0 flex-col"><div className="shrink-0 border-b border-line bg-surface/40"><Balance rounds={state.rounds} /></div><div className="min-h-0 flex-1"><Debate state={state} onOpen={setOpenEvidence} /></div><Outcome state={state} onOpenCaseFile={() => setCaseFileOpen(true)} /></section>
        </div>
      </div>
      <DemoControls listingId={state.listing?.id ?? null} events={events} speed={speed} onSpeed={setSpeed} />
      <EvidenceDrawer evidence={openEvidence ? state.evidence[openEvidence] ?? null : null} listing={state.listing} onClose={() => setOpenEvidence(null)} />
      <CaseFileDrawer caseFile={state.caseFile} evidence={state.evidence} open={caseFileOpen} onClose={() => setCaseFileOpen(false)} onOpenEvidence={setOpenEvidence} />
    </div>
  );
}

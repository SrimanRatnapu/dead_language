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

// One screen for live cases, recorded replays and the fixture: all state comes from events.
export function CaseView({ target }: { target: CaseTarget }) {
  const [speed, setSpeed] = useState<Speed>(1);
  const source = useMemo<CaseSource>(() => (target.kind === "live" ? target : { ...target, speed }), [target, speed]);
  const events = useCaseEvents(source);
  const { state } = events;

  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [caseFileOpen, setCaseFileOpen] = useState(false);

  return (
    <div className="flex h-[calc(100dvh-3rem)] flex-col">
      {events.error && (
        <p className="shrink-0 bg-red-tint px-6 py-1.5 text-red">
          {events.error} <Link href="/" className="underline underline-offset-2">Back to the demo</Link>
        </p>
      )}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(360px,34%)_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-y-auto border-r border-line bg-surface">
          <DecodedListing state={state} onOpenEvidence={setOpenEvidence} />
        </aside>
        <section className="flex min-h-0 flex-col">
          <div className="shrink-0 border-b border-line"><Balance rounds={state.rounds} /></div>
          <div className="min-h-0 flex-1"><Debate state={state} onOpen={setOpenEvidence} /></div>
          <Outcome state={state} onOpenCaseFile={() => setCaseFileOpen(true)} />
        </section>
      </div>
      <DemoControls listingId={state.listing?.id ?? null} events={events} speed={speed} onSpeed={setSpeed} />
      <EvidenceDrawer evidence={openEvidence ? state.evidence[openEvidence] ?? null : null} listing={state.listing} onClose={() => setOpenEvidence(null)} />
      <CaseFileDrawer caseFile={state.caseFile} evidence={state.evidence} open={caseFileOpen} onClose={() => setCaseFileOpen(false)} onOpenEvidence={setOpenEvidence} />
    </div>
  );
}

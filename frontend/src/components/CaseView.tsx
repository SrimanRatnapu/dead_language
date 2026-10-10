"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useCaseEvents, type CaseSource, type Speed } from "@/lib/useCaseEvents";
import { CaseFileDrawer } from "./CaseFileDrawer";
import { ConfidenceChart } from "./ConfidenceChart";
import { DemoControls } from "./DemoControls";
import { EvidenceBoard } from "./EvidenceBoard";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { ListingPanel } from "./ListingPanel";
import { OutcomeBanner } from "./OutcomeBanner";
import { RoundTimeline } from "./RoundTimeline";
import { SpecialistFeed } from "./SpecialistFeed";

export type CaseTarget = { kind: "live"; caseId: string } | { kind: "replay"; name: string } | { kind: "fixture" };

function PanelTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="sticky top-0 z-[1] bg-bg/90 px-4 py-2 font-semibold backdrop-blur">{children}</h2>;
}

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
      {(events.offline || events.error) && (
        <p className="shrink-0 bg-sunken px-5 py-1.5 text-muted">
          {events.error ?? "Backend offline — playing a recorded case."}{" "}
          <Link href="/" className="underline underline-offset-2">Back to listings</Link>
        </p>
      )}
      <div className="h-36 shrink-0 border-b border-line"><ConfidenceChart rounds={state.rounds} /></div>

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_340px]">
        <aside className="min-h-0 overflow-y-auto border-r border-line"><ListingPanel state={state} onOpenEvidence={setOpenEvidence} /></aside>
        <main className="min-h-0"><RoundTimeline state={state} onOpen={setOpenEvidence} /></main>
        <aside className="flex min-h-0 flex-col border-l border-line">
          <div className="min-h-0 flex-[3] overflow-y-auto">
            <PanelTitle>Evidence</PanelTitle>
            <div className="px-3 pb-3"><EvidenceBoard state={state} onOpen={setOpenEvidence} /></div>
          </div>
          <div className="min-h-0 flex-[2] overflow-y-auto border-t border-line">
            <PanelTitle>Specialists</PanelTitle>
            <div className="px-4 pb-3"><SpecialistFeed state={state} /></div>
          </div>
        </aside>
      </div>

      <OutcomeBanner state={state} onOpenCaseFile={() => setCaseFileOpen(true)} />
      <DemoControls listingId={state.listing?.id ?? null} events={events} speed={speed} onSpeed={setSpeed} />
      <EvidenceDrawer evidence={openEvidence ? state.evidence[openEvidence] ?? null : null} listing={state.listing} onClose={() => setOpenEvidence(null)} />
      <CaseFileDrawer caseFile={state.caseFile} open={caseFileOpen} onClose={() => setCaseFileOpen(false)} onOpenEvidence={setOpenEvidence} />
    </div>
  );
}

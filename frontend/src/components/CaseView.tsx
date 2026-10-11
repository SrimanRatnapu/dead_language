"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useCaseEvents, type CaseSource, type Speed } from "@/lib/useCaseEvents";
import { CaseFileDrawer } from "./CaseFileDrawer";
import { DecodedListing } from "./DecodedListing";
import { DemoControls } from "./DemoControls";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { Examination } from "./Examination";
import { Outcome } from "./Outcome";
import { AgentRail, Standing } from "./Seats";
import { StrikeReview } from "./StrikeReview";
import { Thread } from "./Thread";

export type CaseTarget = { kind: "live"; caseId: string } | { kind: "replay"; name: string } | { kind: "fixture" };
type Stage = "listing" | "examiners" | "agents";
const STEPS: { key: Stage; label: string }[] = [{ key: "listing", label: "Listing" }, { key: "examiners", label: "Specialists" }, { key: "agents", label: "Agents" }];

export function CaseView({ target }: { target: CaseTarget }) {
  const [speed, setSpeed] = useState<Speed>(1);
  const source = useMemo<CaseSource>(() => (target.kind === "live" ? target : { ...target, speed }), [target, speed]);
  const events = useCaseEvents(source);
  const { state } = events;
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [caseFileOpen, setCaseFileOpen] = useState(false);
  // Three pages: read the listing, watch the specialists, then the agents discuss. The agents' events are held back until the hand-off.
  const [stage, setStage] = useState<Stage>("listing");
  const ready = events.held || state.rounds.length > 0;
  const toAgents = () => { events.release(); setStage("agents"); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { const s = new URLSearchParams(location.search).get("stage"); if (s === "agents") toAgents(); else if (s === "examiners") setStage("examiners"); }, []);
  const go = (k: Stage) => (k === "agents" ? toAgents() : setStage(k));
  // scripts/record_scripted_demo.py stamps its runs with a "DEMO-" case id; recorded live runs are "C-0001".
  const scripted = Object.values(state.evidence)[0]?.case_id.startsWith("DEMO-") ?? false;
  const flagged = target.kind === "live" && (state.caseFile?.outcome === "FILE" || state.caseFile?.outcome === "CONTESTED");

  return (
    <main className="shell-grid flex h-[calc(100dvh-3.5rem)] flex-col overflow-hidden">
      {events.error && <p className="shrink-0 border-b border-red/30 bg-red-tint px-6 py-2 text-red">{events.error} <Link href="/desk" className="underline underline-offset-2">Back to the desk</Link></p>}
      <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 flex-col px-4 py-3 sm:px-6 lg:px-8">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2">
          <div className="flex items-center gap-4">
            <Link href="/desk" className="press -ml-2 inline-flex min-h-11 items-center px-3 text-sm text-muted hover:text-cobalt-ink lg:min-h-0">← Review desk</Link>
            <nav aria-label="Pages" className="flex items-center gap-1 text-sm">
              {STEPS.map((st, i) => (
                <button key={st.key} disabled={st.key === "agents" && !ready} onClick={() => go(st.key)} aria-current={stage === st.key ? "step" : undefined}
                  className={`press inline-flex min-h-11 items-center gap-2 px-2 lg:min-h-0 lg:py-1.5 ${stage === st.key ? "font-semibold text-ink" : "text-muted enabled:hover:text-ink disabled:opacity-40"}`}>
                  <span className={`grid size-6 place-items-center text-sm ${stage === st.key ? "bg-cobalt text-white" : "bg-sunken"}`}>{i + 1}</span>{st.label}
                </button>
              ))}
            </nav>
          </div>
          <DemoControls events={events} speed={speed} onSpeed={setSpeed} />
        </div>
        {scripted && <details className="mb-2 text-sm text-muted"><summary className="press inline-flex min-h-11 cursor-pointer items-center text-amber-ink lg:min-h-0">Scripted walkthrough</summary><p className="pb-2">Evidence and rules ran on real data. The agents' wording and photo readings are scripted.</p></details>}

        <div className="flex min-h-0 flex-1 flex-col">
          {stage === "listing" && <>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <DecodedListing state={state} onOpenEvidence={setOpenEvidence} />
              <div className="mx-auto flex max-w-[1100px] justify-end pb-6 pt-4">
                <button onClick={() => setStage("examiners")} className="press min-h-11 bg-ink px-5 py-2.5 font-semibold text-surface hover:bg-cobalt">See what the specialists found →</button>
              </div>
            </div>
          </>}
          {stage === "examiners" && <Examination state={state} ready={ready} onBack={() => setStage("listing")} onSend={toAgents} onOpen={setOpenEvidence} />}
          {stage === "agents" && <>
            <Standing state={state} />
            <div className="grid min-h-0 flex-1 lg:grid-cols-[17rem_1fr]">
              <aside aria-label="Who is in the discussion" className="max-h-[30dvh] overflow-y-auto border-b border-line lg:max-h-none lg:border-b-0 lg:border-r"><AgentRail state={state} onOpen={setOpenEvidence} /></aside>
              <section aria-label="Discussion" className="min-h-0">
                <Thread state={state} onOpen={setOpenEvidence}>
                  <Outcome state={state} onOpenCaseFile={() => setCaseFileOpen(true)} />
                  {flagged && target.kind === "live" && <StrikeReview caseId={target.caseId} />}
                </Thread>
              </section>
            </div>
          </>}
        </div>
      </div>
      <EvidenceDrawer evidence={openEvidence ? state.evidence[openEvidence] ?? null : null} listing={state.listing} onClose={() => setOpenEvidence(null)} />
      <CaseFileDrawer caseFile={state.caseFile} evidence={state.evidence} open={caseFileOpen} onClose={() => setCaseFileOpen(false)} onOpenEvidence={setOpenEvidence} />
    </main>
  );
}

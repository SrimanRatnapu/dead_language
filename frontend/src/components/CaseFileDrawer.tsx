"use client";
import { AGENT_ORDER, AGENTS, OUTCOME_LABEL, STANCE_LABEL } from "@/lib/agents";
import type { CaseFile } from "@/lib/types";
import { Drawer } from "./Drawer";
import { EvidenceChip } from "./EvidenceChip";
import { StanceMark } from "./StanceMark";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="font-semibold">{title}</h3>
      {children}
    </section>
  );
}

export function CaseFileDrawer({ caseFile, open, onClose, onOpenEvidence }: { caseFile: CaseFile | null; open: boolean; onClose: () => void; onOpenEvidence: (id: string) => void }) {
  return (
    <Drawer open={open && !!caseFile} title={caseFile ? `Case file · ${OUTCOME_LABEL[caseFile.outcome]}` : "Case file"} onClose={onClose}>
      {caseFile && (
        <div className="flex flex-col gap-6">
          <p className="rounded-md bg-sunken px-3 py-2 text-muted">Prepared for human review — not sent</p>

          {caseFile.tip_draft && (
            <Section title="Tip draft">
              <pre className="mono whitespace-pre-wrap rounded-lg border border-line bg-sunken p-3 leading-relaxed">{caseFile.tip_draft}</pre>
            </Section>
          )}

          <Section title="Final positions">
            <ul className="flex flex-col gap-2">
              {AGENT_ORDER.map((a) => {
                const p = caseFile.final_positions.find((x) => x.agent === a);
                if (!p) return null;
                return (
                  <li key={a} className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                      <span className={`font-semibold ${AGENTS[a].text}`}>{AGENTS[a].label}</span>
                      <StanceMark stance={p.stance} size={8} />
                      {STANCE_LABEL[p.stance]} <span className="mono text-muted">{p.confidence.toFixed(2)}</span>
                    </span>
                    {p.claims.map((c, i) => (
                      <span key={i} className="text-muted">
                        {c.text}{" "}
                        {c.evidence_ids.map((id) => <EvidenceChip key={id} id={id} onOpen={onOpenEvidence} />)}
                      </span>
                    ))}
                  </li>
                );
              })}
            </ul>
          </Section>

          <Section title="Legal basis">
            {caseFile.legal_basis.length ? (
              <ul className="list-disc pl-5">{caseFile.legal_basis.map((l) => <li key={l}>{l}</li>)}</ul>
            ) : <p className="text-muted">None recorded.</p>}
          </Section>

          <Section title="Linked sellers">
            {caseFile.linked_seller_ids.length ? (
              <p className="flex flex-wrap gap-1.5">{caseFile.linked_seller_ids.map((s) => <span key={s} className="mono rounded bg-sunken px-1.5">{s}</span>)}</p>
            ) : <p className="text-muted">None found.</p>}
          </Section>
        </div>
      )}
    </Drawer>
  );
}

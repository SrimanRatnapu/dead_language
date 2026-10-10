"use client";
import { useState } from "react";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Photo } from "./Photo";

export function ListingPanel({ state, onOpenEvidence }: { state: CaseState; onOpenEvidence: (id: string) => void }) {
  const { listing, seller, removed, evidence, evidenceOrder } = state;
  const [selected, setSelected] = useState(0);

  if (!listing) return <div className="p-4 text-muted">Loading listing…</div>;

  // Latest material exam finding per photo index.
  const exams = new Map<number, { id: string; features: string; material: string }>();
  for (const id of evidenceOrder) {
    const ev = evidence[id];
    if (ev.capability !== "material_exam" || typeof ev.data.photo_index !== "number") continue;
    exams.set(ev.data.photo_index, { id, features: String(ev.data.features ?? ""), material: String(ev.data.material ?? "") });
  }
  const exam = exams.get(selected);

  return (
    <div className="relative flex flex-col gap-4 p-4">
      {removed && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 bg-bg/85 p-6 text-center">
          <p className="display text-xl">Removed by seller</p>
          <p className="text-muted">
            Snapshot kept as{" "}
            <button onClick={() => onOpenEvidence("E0")} className="mono underline underline-offset-2">E0</button>
          </p>
          {removed.relisted_as && <p className="text-muted">Relisted as <span className="mono">{removed.relisted_as}</span></p>}
        </div>
      )}

      {listing.image_paths.length > 0 && (
        <div className="flex flex-col gap-2">
          <Photo src={imageUrl(listing.image_paths[selected])} label={`Photo ${selected}`} className="aspect-[4/3] w-full rounded-lg border border-line" />
          {exam && (
            <button onClick={() => onOpenEvidence(exam.id)} className="rounded-lg border border-amber bg-amber-tint p-2 text-left text-amber-ink">
              <span className="mono">{exam.id}</span> · {exam.material.replaceAll("_", " ")}: {exam.features}
            </button>
          )}
          <div className="flex gap-2">
            {listing.image_paths.map((p, i) => (
              <button
                key={p}
                onClick={() => setSelected(i)}
                aria-label={`Show photo ${i}`}
                aria-pressed={i === selected}
                className={`press overflow-hidden rounded-md border-2 ${exams.has(i) ? "border-amber" : i === selected ? "border-ink" : "border-transparent"}`}
              >
                <Photo src={imageUrl(p)} label={`${i}`} className="size-14" />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <h1 className="display text-xl">{listing.title}</h1>
        <p className="text-2xl font-semibold tracking-tight">{usd(listing.price_usd)}</p>
        {listing.is_reconstructed && (
          <p className="w-fit rounded bg-sunken px-2 py-0.5 text-muted">Reconstructed from a documented case</p>
        )}
      </div>

      <p className="text-ink/90">{listing.description}</p>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted">Stated material</dt><dd>{listing.stated_material.replaceAll("_", " ")}</dd>
        <dt className="text-muted">Ships from</dt><dd>{listing.ship_from}</dd>
        <dt className="text-muted">Seller</dt><dd>{seller?.name} <span className="mono text-muted">{listing.seller_id}</span></dd>
        {listing.relist_of && (<><dt className="text-muted">Relist of</dt><dd className="mono">{listing.relist_of}</dd></>)}
      </dl>
    </div>
  );
}

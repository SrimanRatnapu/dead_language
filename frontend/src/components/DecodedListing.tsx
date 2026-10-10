"use client";
import { useState } from "react";
import Link from "next/link";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Photo } from "./Photo";

interface Mark { text: string; gloss: string }

function examFor(e: CaseState["evidence"][string], photoIndex?: number) {
  const legacyIndex = e.data.photo_index;
  const photo = Array.isArray(e.data.photos)
    ? e.data.photos.find((item) => item && typeof item === "object" && item.index === photoIndex)
    : undefined;
  const index = typeof legacyIndex === "number" ? legacyIndex : photo?.index;
  const material = typeof e.data.material === "string" ? e.data.material : photo?.material ?? e.data.overall;
  const features = typeof e.data.features === "string" ? e.data.features : photo?.visible_features?.join(", ");
  return { index, material: typeof material === "string" ? material : "cannot_tell", features };
}

function linkedDetails(e: CaseState["evidence"][string] | undefined) {
  if (!e) return { phrases: [] as string[], count: 0 };
  const data = e.data;
  const linked = Array.isArray(data.linked) ? data.linked : [];
  return {
    phrases: Array.from(new Set([
      ...(Array.isArray(data.shared_phrases) ? data.shared_phrases : []),
      ...linked.flatMap((item) => Array.isArray(item?.shared_phrases) ? item.shared_phrases : []),
    ])).filter((phrase): phrase is string => typeof phrase === "string"),
    count: typeof data.linked_seller_count === "number"
      ? data.linked_seller_count
      : Array.isArray(data.linked_sellers) ? data.linked_sellers.length : linked.length,
  };
}

// Wrap each coded phrase in <ruby> (native interlinear annotation) once evidence explains it.
function annotate(description: string, marks: Mark[]): React.ReactNode[] {
  const lower = description.toLowerCase();
  const found = marks
    .map((m) => ({ ...m, at: lower.indexOf(m.text.toLowerCase()) }))
    .filter((m) => m.at >= 0)
    .sort((a, b) => a.at - b.at);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  for (const m of found) {
    if (m.at < cursor) continue;
    out.push(description.slice(cursor, m.at));
    out.push(
      <ruby key={m.at} className="decoded px-0.5">
        {description.slice(m.at, m.at + m.text.length)}
        <rt>{m.gloss}</rt>
      </ruby>,
    );
    cursor = m.at + m.text.length;
  }
  out.push(description.slice(cursor));
  return out;
}

export function DecodedListing({ state, onOpenEvidence }: { state: CaseState; onOpenEvidence: (id: string) => void }) {
  const { listing, seller, removed, evidence, evidenceOrder } = state;
  const [selected, setSelected] = useState(0);
  if (!listing) return <p className="p-6 text-muted">Loading listing…</p>;

  const all = evidenceOrder.map((id) => evidence[id]);
  const exams = all.filter((e) => e.capability === "material_exam");
  const decisive = [...exams].reverse().map((e) => examFor(e)).find((e) => e.material !== "cannot_tell");
  const examHere = [...exams].reverse().map((e) => ({ evidence: e, result: examFor(e, selected) }))
    .find((entry) => entry.result.index === selected);
  const ratio = all.find((e) => e.capability === "price_check")?.data.ratio_to_median;
  const linked = linkedDetails(all.find((e) => e.capability === "linked_sellers"));
  const material = decisive ? decisive.material.replaceAll("_", " ") : null;
  const stated = listing.stated_material.replaceAll("_", " ");

  const marks: Mark[] = [
    ...linked.phrases.map((p) => ({ text: p, gloss: `used by ${linked.count} other seller${linked.count === 1 ? "" : "s"}` })),
    ...(material ? [{ text: stated, gloss: `photo says ${material}` }] : []),
  ];

  return (
    <div className="relative flex flex-col gap-5 p-6">
      <Link href="/" className="w-fit text-muted hover:text-ink">← Back</Link>

      {removed && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 bg-bg/90 p-6 text-center">
          <p className="display text-3xl">Removed by seller</p>
          <p className="text-muted">
            The page was saved first.{" "}
            <button onClick={() => onOpenEvidence(evidenceOrder[0])} className="underline underline-offset-2">View snapshot</button>
          </p>
          {removed.relisted_as && <p className="text-muted">It has already reappeared under a new account.</p>}
        </div>
      )}

      {listing.image_paths.length > 0 && (
        <div className="flex flex-col gap-2">
          <Photo src={imageUrl(listing.image_paths[selected])} label={`Photo ${selected + 1}`} className="aspect-[4/3] w-full rounded-xl" caption="Photo unavailable offline" />
          {examHere?.result.features && (
            <button onClick={() => onOpenEvidence(examHere.evidence.id)} className="rise rounded-lg bg-amber-tint px-3 py-2 text-left font-medium text-amber-ink">
              {examHere.result.features}
            </button>
          )}
          {listing.image_paths.length > 1 && (
            <div className="flex gap-2">
              {listing.image_paths.map((p, i) => (
                <button
                  key={p}
                  onClick={() => setSelected(i)}
                  aria-label={`Show photo ${i + 1}`}
                  aria-pressed={i === selected}
                  className={`press overflow-hidden rounded-md border-2 ${exams.some((e) => examFor(e, i).index === i) ? "border-amber" : i === selected ? "border-ink" : "border-transparent"}`}
                >
                  <Photo src={imageUrl(p)} label={`Photo ${i + 1}`} className="size-12" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <h1 className="display text-[2rem]">{listing.title}</h1>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-2xl font-semibold tracking-tight">{usd(listing.price_usd)}</span>
          {typeof ratio === "number" && (
            <span className="rise font-medium text-amber-ink">{ratio.toFixed(ratio < 10 ? 1 : 0)}× the usual price</span>
          )}
        </div>
        <p className="mt-1 text-muted">
          Listed as <span className={material ? "text-ink line-through decoration-amber decoration-2" : "text-ink"}>{stated}</span>
          {material && <span className="rise font-semibold text-amber-ink"> → looks like {material}</span>}
        </p>
      </div>

      <p className="text-[1.05rem] leading-[2.6]">{annotate(listing.description, marks)}</p>

      <p className="text-muted">
        Sold by {seller?.name}, shipping from {listing.ship_from}.
        {listing.is_reconstructed && " Reconstructed from a documented case."}
      </p>
    </div>
  );
}

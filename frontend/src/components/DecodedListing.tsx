"use client";
import { useState } from "react";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Photo } from "./Photo";

interface Mark { text: string; gloss: string }
function examFor(e: CaseState["evidence"][string], photoIndex?: number) {
  const photo = Array.isArray(e.data.photos) ? e.data.photos.find((item) => item && typeof item === "object" && item.index === photoIndex) : undefined;
  const index = typeof e.data.photo_index === "number" ? e.data.photo_index : photo?.index;
  const material = typeof e.data.material === "string" ? e.data.material : photo?.material ?? e.data.overall;
  return { index, material: typeof material === "string" ? material : "cannot_tell", features: typeof e.data.features === "string" ? e.data.features : photo?.visible_features?.join(", ") };
}
function linkedDetails(e: CaseState["evidence"][string] | undefined) {
  if (!e) return { phrases: [] as string[], count: 0 };
  const linked = Array.isArray(e.data.linked) ? e.data.linked : [];
  return { phrases: linked.flatMap((x) => typeof x === "object" && x ? [...(typeof x.phrase === "string" ? [x.phrase] : []), ...(Array.isArray(x.shared_phrases) ? x.shared_phrases.filter((p: unknown): p is string => typeof p === "string") : [])] : []), count: linked.length };
}
function annotate(description: string, marks: Mark[]): React.ReactNode[] {
  const lower = description.toLowerCase(); const found = marks.map((m) => ({ ...m, at: lower.indexOf(m.text.toLowerCase()) })).filter((m) => m.at >= 0).sort((a, b) => a.at - b.at); const out: React.ReactNode[] = []; let cursor = 0;
  for (const m of found) { if (m.at < cursor) continue; out.push(description.slice(cursor, m.at)); out.push(<span key={`${m.text}-${m.at}`} className="decoded" title={m.gloss}>{description.slice(m.at, m.at + m.text.length)}</span>); cursor = m.at + m.text.length; }
  out.push(description.slice(cursor)); return out;
}

export function DecodedListing({ state, onOpenEvidence }: { state: CaseState; onOpenEvidence: (id: string) => void }) {
  const { listing, seller, removed, evidence, evidenceOrder } = state; const [selected, setSelected] = useState(0);
  if (!listing) return <p className="p-6 text-muted">Loading listing…</p>;
  const all = evidenceOrder.map((id) => evidence[id]); const exams = all.filter((e) => e.capability === "material_exam");
  const decisive = [...exams].reverse().map((e) => examFor(e)).find((e) => e.material !== "cannot_tell");
  const examHere = [...exams].reverse().map((e) => ({ evidence: e, result: examFor(e, selected) })).find((entry) => entry.result.index === selected);
  const priceData = all.find((e) => e.capability === "price_check")?.data; const ratio = priceData?.ratio ?? priceData?.ratio_to_median; const linked = linkedDetails([...all].reverse().find((e) => e.capability === "linked_sellers")); const material = decisive?.material.replaceAll("_", " "); const stated = listing.stated_material.replaceAll("_", " ");
  const marks: Mark[] = Array.from(new Map([...linked.phrases.map((p) => ({ text: p, gloss: `used by ${linked.count} other seller${linked.count === 1 ? "" : "s"}` })), ...(material ? [{ text: stated, gloss: `photo says ${material}` }] : [])].map((m) => [m.text.toLowerCase(), m])).values());
  return <div className="relative flex flex-col gap-3 p-4">
    {removed && <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-bg/95 p-6 text-center"><p className="display text-3xl">Removed by seller</p><button onClick={() => onOpenEvidence(evidenceOrder[0])} className="press border border-line px-3 py-2 hover:border-cobalt">View snapshot</button></div>}
    <div><h1 className="display text-xl">{listing.title}</h1><div className="mt-1.5 flex items-baseline justify-between gap-3"><span className="text-2xl font-semibold tracking-tight text-cobalt-ink">{usd(listing.price_usd)}</span>{typeof ratio === "number" && <span className="mono text-amber-ink">{ratio.toFixed(ratio < 10 ? 1 : 0)}× MARKET</span>}</div></div>
    {listing.image_paths.length > 0 && <div className="flex flex-col gap-2"><div className="relative overflow-hidden border border-line"><Photo src={imageUrl(listing.image_paths[selected])} label={`Photo ${selected + 1}`} className="aspect-[16/9] w-full" caption="Photo unavailable offline" /><span className="absolute left-0 top-0 bg-bg/90 px-2 py-1 mono">{String(selected + 1).padStart(2, "0")}</span></div>{examHere?.result.features && <button onClick={() => onOpenEvidence(examHere.evidence.id)} className="rise border-l-2 border-amber bg-amber-tint px-3 py-2 text-left text-sm font-medium text-amber-ink">{examHere.result.features}</button>}{listing.image_paths.length > 1 && <div className="flex gap-2">{listing.image_paths.map((p, i) => <button key={p} onClick={() => setSelected(i)} aria-label={`Show photo ${i + 1}`} aria-pressed={i === selected} className={`press overflow-hidden border-2 ${i === selected ? "border-cobalt" : "border-transparent opacity-60 hover:opacity-100"}`}><Photo src={imageUrl(p)} label={`Photo ${i + 1}`} className="size-11" /></button>)}</div>}</div>}
    <div className="border-y border-line py-2"><p className="rule-label">Stated material</p><p className="text-muted">{material ? <><span className="text-ink line-through decoration-amber decoration-2">{stated}</span><span className="ml-2 font-semibold text-amber-ink">looks like {material}</span></> : stated}</p></div>
    <div><p className="text-base leading-7">{annotate(listing.description, marks)}</p>{marks.length > 0 && <ul className="mt-3 flex flex-col gap-1 text-sm text-muted">{marks.map((m) => <li key={m.text}><span className="decoded text-ink">{m.text}</span> <span className="text-amber-ink">{m.gloss}</span></li>)}</ul>}</div><p className="border-t border-line pt-2 text-sm text-muted">Sold by <span className="text-ink">{seller?.name}</span> · Ships from {listing.ship_from}{listing.is_reconstructed && " · reconstructed from a documented case"}</p>
  </div>;
}

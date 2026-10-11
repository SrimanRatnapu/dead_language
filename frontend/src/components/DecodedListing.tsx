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
  const imgs = listing.image_paths;
  const specifics: [string, React.ReactNode][] = [
    ["Material", material ? <><span className="line-through decoration-amber decoration-2">{stated}</span><span className="ml-2 font-semibold text-amber-ink">looks like {material}</span></> : stated],
    ["Type", listing.item_type.replaceAll("_", " ")],
    ...(listing.size_cm ? [["Size", `${listing.size_cm} cm`] as [string, string]] : []),
    ...(listing.weight_g ? [["Weight", `${listing.weight_g} g`] as [string, string]] : []),
    ["Ships from", listing.ship_from],
    ["Listed", new Date(listing.posted_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })],
  ];
  return <div className="relative px-4 py-4 sm:px-8">
    {removed && <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-bg/95 p-6 text-center"><p className="display text-3xl">Removed by seller</p><button onClick={() => onOpenEvidence(evidenceOrder[0])} className="press border border-line px-3 py-2 hover:border-cobalt">View snapshot</button></div>}
    <div className="mx-auto grid max-w-[1100px] gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      {imgs.length > 0 && <div className="flex flex-col-reverse gap-3 sm:flex-row">
        {imgs.length > 1 && <div className="flex gap-2 sm:flex-col">{imgs.map((p, i) => <button key={p} onClick={() => setSelected(i)} aria-label={`Show photo ${i + 1}`} aria-pressed={i === selected} className={`press shrink-0 overflow-hidden outline-offset-0 ${i === selected ? "outline outline-2 outline-ink" : "opacity-70 hover:opacity-100"}`}><Photo src={imageUrl(p)} label={`Photo ${i + 1}`} className="size-16" /></button>)}</div>}
        <div className="min-w-0 flex-1">
          <Photo src={imageUrl(imgs[selected])} label={`Photo ${selected + 1}`} className="aspect-square w-full bg-bg" caption="Photo unavailable offline" />
          {examHere?.result.features && <button onClick={() => onOpenEvidence(examHere.evidence.id)} className="rise mt-2 block w-full bg-amber-tint px-3 py-2 text-left text-sm font-medium text-amber-ink">{examHere.result.features}</button>}
        </div>
      </div>}
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold leading-snug [text-wrap:balance]">{listing.title}</h1>
        <p className="mt-4 flex flex-wrap items-baseline gap-x-3"><span className="text-3xl font-bold tracking-tight">{usd(listing.price_usd)}</span>{typeof ratio === "number" && <span className="rise font-semibold text-amber-ink">{ratio.toFixed(ratio < 10 ? 1 : 0)}× the usual price</span>}</p>
                <dl className="mt-6 grid grid-cols-[7rem_1fr] gap-x-4 gap-y-2.5 border-t border-line pt-5">
          {specifics.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="capitalize-first">{v}</dd></div>)}
        </dl>
        {seller && <p className="mt-6 flex items-center gap-3 border-t border-line pt-5"><span className="grid size-10 shrink-0 place-items-center rounded-full bg-sunken font-semibold">{seller.name[0]?.toUpperCase()}</span><span className="leading-snug"><span className="font-semibold">{seller.name}</span><span className="block text-sm text-muted">{seller.location}{seller.feedback_score != null ? ` · ${seller.feedback_score}% positive` : ""}{seller.joined ? ` · joined ${new Date(seller.joined).toLocaleDateString(undefined, { year: "numeric", month: "short" })}` : ""}</span></span></p>}
      </div>
    </div>
    <section className="mx-auto mt-5 max-w-[1100px] border-t border-line pt-5">
      <h2 className="font-semibold">Item description from the seller</h2>
      <p className="mt-3 max-w-[70ch] text-base leading-7">{annotate(listing.description, marks)}</p>
      {marks.length > 0 && <ul className="mt-3 flex flex-col gap-1 text-sm text-muted">{marks.map((m) => <li key={m.text}><span className="decoded text-ink">{m.text}</span> <span className="text-amber-ink">{m.gloss}</span></li>)}</ul>}
    </section>
  </div>;
}

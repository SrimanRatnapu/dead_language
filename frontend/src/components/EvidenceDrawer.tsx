"use client";
import { imageUrl } from "@/lib/api";
import { CAPABILITY_LABEL } from "@/lib/agents";
import type { Evidence, Listing } from "@/lib/types";
import { Drawer } from "./Drawer";
import { Photo } from "./Photo";

export function EvidenceDrawer({ evidence, listing, onClose }: { evidence: Evidence | null; listing: Listing | null; onClose: () => void }) {
  const photoIdx = evidence?.capability === "material_exam" ? Number(evidence.data.photo_index) : NaN;
  const photo = listing && Number.isInteger(photoIdx) ? listing.image_paths[photoIdx] : undefined;
  return <Drawer open={!!evidence} title={evidence ? CAPABILITY_LABEL[evidence.capability] : "Evidence"} onClose={onClose}>{evidence && <div className="flex flex-col gap-5"><div className="border-b border-line pb-4"><p className="rule-label mb-2">Evidence record</p><p className="text-lg leading-relaxed">{evidence.summary}</p><p className="mt-3 mono text-muted">{evidence.produced_by === "code" ? "CHECKED BY CODE" : `AI READING · ${Math.round((evidence.confidence ?? 0) * 100)}% CONFIDENCE`} · {evidence.specialist_name}</p></div>{photo && <figure className="overflow-hidden border border-line"><Photo src={imageUrl(photo)} label={`Photo ${photoIdx + 1}`} caption="Photo unavailable offline" className="aspect-[4/3] w-full" /><figcaption className="rule-label px-3 py-2">Referenced photograph {photoIdx + 1}</figcaption></figure>}<div><p className="rule-label mb-2">Source payload</p><pre className="mono overflow-x-auto border border-line bg-sunken p-3 leading-relaxed">{JSON.stringify(evidence.data, null, 2)}</pre></div></div>}</Drawer>;
}

"use client";
import { imageUrl } from "@/lib/api";
import { CAPABILITY_LABEL } from "@/lib/agents";
import type { Evidence, Listing } from "@/lib/types";
import { Drawer } from "./Drawer";
import { Photo } from "./Photo";

export function EvidenceDrawer({ evidence, listing, onClose }: { evidence: Evidence | null; listing: Listing | null; onClose: () => void }) {
  const photoIdx = evidence?.capability === "material_exam" ? Number(evidence.data.photo_index) : NaN;
  const photo = listing && Number.isInteger(photoIdx) ? listing.image_paths[photoIdx] : undefined;

  return (
    <Drawer open={!!evidence} title={evidence ? `${evidence.id} · ${CAPABILITY_LABEL[evidence.capability]}` : "Evidence"} onClose={onClose}>
      {evidence && (
        <div className="flex flex-col gap-4">
          <p className="text-base">{evidence.summary}</p>
          <p className="text-muted">
            {evidence.produced_by === "code" ? "Computed by code" : `AI reading · confidence ${evidence.confidence ?? "n/a"}`}
            {" · "}from <span className="mono">{evidence.specialist_name}</span>
            {" · "}requested by {evidence.requested_by}
          </p>
          {photo && (
            <figure className="overflow-hidden rounded-lg border border-line">
              <Photo src={imageUrl(photo)} label={`Photo ${photoIdx}`} className="aspect-[4/3] w-full" />
            </figure>
          )}
          <pre className="mono overflow-x-auto rounded-lg border border-line bg-sunken p-3 leading-relaxed">
            {JSON.stringify(evidence.data, null, 2)}
          </pre>
        </div>
      )}
    </Drawer>
  );
}

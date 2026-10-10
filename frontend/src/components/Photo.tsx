"use client";
import { useState } from "react";
import { API_BASE } from "@/lib/api";

// Images come from the backend; when it is offline the exported copy in public/images is tried,
// and a quiet tile holds the layout if neither exists.
export function Photo({ src, label, className = "", caption }: { src: string; label: string; className?: string; caption?: string }) {
  const [stage, setStage] = useState<"api" | "static" | "failed">("api");
  if (stage === "failed") {
    return (
      <div className={`flex items-center justify-center bg-sunken text-muted ${className}`} role="img" aria-label={`${label} unavailable`}>
        {caption && <span>{caption}</span>}
      </div>
    );
  }
  const local = src.replace(`${API_BASE}/api/images/`, "/");   // ".../api/images/images/L1_0.jpg" -> "/images/L1_0.jpg"
  const url = stage === "api" ? src : local;
  // eslint-disable-next-line @next/next/no-img-element -- remote API images, sized by the caller
  return <img src={url} alt={label} onError={() => setStage(stage === "api" && local !== src ? "static" : "failed")} className={`object-cover ${className}`} />;
}

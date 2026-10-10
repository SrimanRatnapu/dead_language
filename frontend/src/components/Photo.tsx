"use client";
import { useState } from "react";

// Images come from the backend; fall back to a labeled tile so layout holds when it is offline.
export function Photo({ src, label, className = "" }: { src: string; label: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className={`flex items-center justify-center bg-sunken text-muted ${className}`} role="img" aria-label={`${label} unavailable`}>
        <span className="mono">{label}</span>
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element -- remote API images, sized by the caller
  return <img src={src} alt={label} onError={() => setFailed(true)} className={`object-cover ${className}`} />;
}

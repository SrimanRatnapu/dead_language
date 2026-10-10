"use client";
import { useState } from "react";

// Images come from the backend; a quiet tile holds the layout when it is offline.
export function Photo({ src, label, className = "", caption }: { src: string; label: string; className?: string; caption?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className={`flex items-center justify-center bg-sunken text-muted ${className}`} role="img" aria-label={`${label} unavailable`}>
        {caption && <span>{caption}</span>}
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element -- remote API images, sized by the caller
  return <img src={src} alt={label} onError={() => setFailed(true)} className={`object-cover ${className}`} />;
}

import type { Stance } from "@/lib/types";

// Same shapes as the confidence chart: circle = file, square = dismiss, triangle = needs more.
export function StanceMark({ stance, size = 10, color = "currentColor" }: { stance: Stance; size?: number; color?: string }) {
  const r = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden fill={color}>
      {stance === "file" && <circle cx={r} cy={r} r={r} />}
      {stance === "dismiss" && <rect width={size} height={size} />}
      {stance === "need_more" && <polygon points={`${r},0 ${size},${size} 0,${size}`} />}
    </svg>
  );
}

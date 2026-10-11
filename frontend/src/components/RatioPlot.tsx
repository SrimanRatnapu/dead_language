"use client";
import { useState } from "react";

export interface SignalData {
  dataset: { real_listings: number; planted_cases: number; sellers: number; eval_set: number; museum_photos: number };
  price: { flag_at: number; planted_flagged: number; planted_total: number; real_flagged: number; real_total: number; planted_ratios: number[]; real_ratios: number[] };
  links: { real_linked: number; real_total: number; network_linked: number; network_total: number };
}

const W = 1000, H = 230, PAD = 12, LANE = { real: 78, planted: 156 }, BASE = H - 30;
const TICKS = [0.1, 0.3, 1, 3, 8, 20];
// Deterministic vertical scatter so overlapping prices stay visible as a cloud.
const jitter = (i: number, spread: number) => (((i * 2654435761) % 1000) / 1000 - 0.5) * spread;

/** Each dot is one listing: its price over the median for the same stated material, log scale. */
export function RatioPlot({ price }: { price: SignalData["price"] }) {
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);
  const all = [...price.real_ratios, ...price.planted_ratios].filter((r) => r > 0);
  const lo = Math.log(Math.min(0.1, ...all)), hi = Math.log(Math.max(20, ...all) * 1.15);
  const x = (r: number) => PAD + ((Math.log(Math.max(r, Math.exp(lo))) - lo) / (hi - lo)) * (W - 2 * PAD);
  const dots = (ratios: number[], lane: number, spread: number, fill: string, name: string) =>
    ratios.map((r, i) => {
      const cx = x(r), cy = lane + jitter(i, spread);
      return <circle key={`${name}-${i}`} cx={cx} cy={cy} r={4.5} fill={fill} fillOpacity={0.8} onMouseEnter={() => setHover({ x: cx, y: cy, label: `${name} · ${r}x the usual price` })} onMouseLeave={() => setHover(null)} />;
    });
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label={`Price compared with the usual price for the stated material. ${price.planted_flagged} of ${price.planted_total} reconstructed cases and ${price.real_flagged} of ${price.real_total} real listings are at ${price.flag_at} times or more.`}>
        <line x1={x(price.flag_at)} x2={x(price.flag_at)} y1={14} y2={BASE} stroke="var(--ink)" strokeWidth={1} />
        <text x={x(price.flag_at) + 8} y={26} fontSize={14} fill="var(--ink)" fontWeight={600}>{price.flag_at}x and above</text>
        {[LANE.real, LANE.planted].map((y) => <line key={y} x1={PAD} x2={W - PAD} y1={y + 24} y2={y + 24} stroke="var(--line)" strokeDasharray="1 5" />)}
        {TICKS.map((t) => <text key={t} x={x(t)} y={H - 8} fontSize={13} textAnchor="middle" fill="var(--muted)">{t}x</text>)}
        <line x1={PAD} x2={W - PAD} y1={BASE} y2={BASE} stroke="var(--ink)" />
        {dots(price.real_ratios, LANE.real, 40, "var(--cobalt)", "Real listing")}
        {dots(price.planted_ratios, LANE.planted, 16, "var(--amber)", "Reconstructed case")}
        {hover && <g pointerEvents="none"><rect x={Math.min(hover.x + 10, W - 300)} y={hover.y - 34} width={290} height={26} fill="var(--ink)" /><text x={Math.min(hover.x + 20, W - 290)} y={hover.y - 16} fontSize={14} fill="var(--surface)">{hover.label}</text></g>}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
        <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-full bg-cobalt" />Real listings ({price.real_total} with enough comparables)</span>
        <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-full bg-amber" />Reconstructed cases ({price.planted_total})</span>
      </figcaption>
    </figure>
  );
}

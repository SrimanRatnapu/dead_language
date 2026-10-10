"use client";
import { useState } from "react";

export interface SignalData {
  dataset: { real_listings: number; planted_cases: number; sellers: number; eval_set: number; museum_photos: number };
  price: { flag_at: number; planted_flagged: number; planted_total: number; real_flagged: number; real_total: number; planted_ratios: number[]; real_ratios: number[] };
  links: { real_linked: number; real_total: number; network_linked: number; network_total: number };
}

const W = 1000, H = 250, PAD_L = 28, PAD_R = 28, LANE = { real: 92, planted: 176 };
const TICKS = [0.1, 0.3, 1, 3, 8, 20];
// Deterministic vertical scatter so overlapping prices stay visible as a cloud.
const jitter = (i: number, spread: number) => (((i * 2654435761) % 1000) / 1000 - 0.5) * spread;

function RatioPlot({ price }: { price: SignalData["price"] }) {
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);
  const all = [...price.real_ratios, ...price.planted_ratios].filter((r) => r > 0);
  const lo = Math.log(Math.min(0.1, ...all)), hi = Math.log(Math.max(20, ...all) * 1.15);
  const x = (r: number) => PAD_L + ((Math.log(Math.max(r, Math.exp(lo))) - lo) / (hi - lo)) * (W - PAD_L - PAD_R);
  const dots = (ratios: number[], lane: number, spread: number, fill: string, name: string) =>
    ratios.map((r, i) => {
      const cx = x(r), cy = lane + jitter(i, spread);
      return <circle key={`${name}-${i}`} cx={cx} cy={cy} r={5} fill={fill} stroke="var(--surface)" strokeWidth={1.5}
        onMouseEnter={() => setHover({ x: cx, y: cy, label: `${name} · ${r}x the usual price` })} onMouseLeave={() => setHover(null)} />;
    });
  return (
    <figure className="mt-6">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label={`Price compared with the usual price for the stated material. ${price.planted_flagged} of ${price.planted_total} reconstructed cases and ${price.real_flagged} of ${price.real_total} real listings are at ${price.flag_at} times or more.`}>
        <rect x={x(price.flag_at)} y={30} width={W - PAD_R - x(price.flag_at)} height={H - 70} fill="var(--amber-tint)" />
        <line x1={x(price.flag_at)} x2={x(price.flag_at)} y1={30} y2={H - 40} stroke="var(--amber)" strokeWidth={2} strokeDasharray="5 5" />
        <text x={x(price.flag_at) + 10} y={48} fontSize={15} fill="var(--amber-ink)" fontWeight={600}>{price.flag_at}x and above</text>
        {TICKS.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={H - 40} y2={H - 34} stroke="var(--line)" />
            <text x={x(t)} y={H - 16} fontSize={14} textAnchor="middle" fill="var(--muted)" fontFamily="var(--font-mono)">{t}x</text>
          </g>
        ))}
        <line x1={PAD_L} x2={W - PAD_R} y1={H - 40} y2={H - 40} stroke="var(--line)" />
        <text x={PAD_L} y={LANE.real - 44} fontSize={15} fill="var(--ink)" fontWeight={600}>Real listings</text>
        <text x={PAD_L} y={LANE.planted - 24} fontSize={15} fill="var(--ink)" fontWeight={600}>Reconstructed cases</text>
        {dots(price.real_ratios, LANE.real, 54, "var(--cobalt)", "Real listing")}
        {dots(price.planted_ratios, LANE.planted, 18, "var(--amber)", "Reconstructed case")}
        {hover && <g pointerEvents="none"><rect x={Math.min(hover.x + 10, W - 300)} y={hover.y - 34} width={290} height={26} rx={4} fill="var(--ink)" /><text x={Math.min(hover.x + 20, W - 290)} y={hover.y - 16} fontSize={14} fill="var(--surface)">{hover.label}</text></g>}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
        <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-full bg-cobalt" />Real listings ({price.real_total} with enough comparables)</span>
        <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-full bg-amber" />Reconstructed cases ({price.planted_total})</span>
        <span>Each dot is one listing: its price divided by the median for the same stated material. Log scale.</span>
      </figcaption>
    </figure>
  );
}

function Tile({ value, label }: { value: string; label: string }) {
  return <div className="bg-surface p-5"><dd className="display text-2xl text-cobalt-ink">{value}</dd><dt className="mt-2 text-muted">{label}</dt></div>;
}

// Numbers computed from the dataset by the code specialists (scripts/export_demo.py). No model involved.
export function Signals({ data }: { data: SignalData }) {
  const { dataset: d, price: p, links: l } = data;
  return (
    <>
      <section aria-labelledby="dataset" className="mt-8">
        <h2 id="dataset" className="rule-label mb-3">What it was tested on</h2>
        <dl className="grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          <Tile value={String(d.real_listings)} label="real marketplace listings, all treated as lawful" />
          <Tile value={String(d.planted_cases)} label="reconstructed trafficking listings, rebuilt from published research" />
          <Tile value={String(d.sellers)} label="sellers, shown only under pseudonyms" />
          <Tile value={String(d.museum_photos)} label="labeled museum photos for testing the photo examiner" />
        </dl>
      </section>

      <section aria-labelledby="price" className="mt-12 border-t border-line pt-8">
        <p className="rule-label mb-3 text-cobalt-ink">Measured by code · no model</p>
        <h2 id="price" className="text-lg font-semibold tracking-tight">Price separates them, but price alone would accuse honest sellers.</h2>
        <RatioPlot price={p} />
        <div className="mt-6 grid gap-px border border-line bg-line md:grid-cols-2">
          <div className="bg-surface p-5"><p className="display text-2xl">{p.planted_flagged} of {p.planted_total}</p><p className="mt-2 text-muted">reconstructed cases are priced at {p.flag_at}x or more. We set those prices to match the documented pattern, so this confirms the dataset rather than proving the method.</p></div>
          <div className="bg-surface p-5"><p className="display text-2xl">{p.real_flagged} of {p.real_total}</p><p className="mt-2 text-muted">real listings are also at {p.flag_at}x or more. A price-only rule would file every one of them. This is the gap the Defender and the photo examiner exist to close.</p></div>
        </div>
      </section>

      <section aria-labelledby="links" className="mt-12 border-t border-line pt-8">
        <p className="rule-label mb-3 text-cobalt-ink">Measured by code · no model</p>
        <h2 id="links" className="text-lg font-semibold tracking-tight">Shared wording and reused photos find the network.</h2>
        <div className="mt-6 grid gap-px border border-line bg-line md:grid-cols-2">
          <div className="bg-surface p-5"><p className="display text-2xl">{l.network_linked} of {l.network_total}</p><p className="mt-2 text-muted">listings in the designed three-seller network are linked to the other sellers by two long shared phrases or a reused photo.</p></div>
          <div className="bg-surface p-5"><p className="display text-2xl">{l.real_linked} of {l.real_total}</p><p className="mt-2 text-muted">real listings are linked to another seller the same way. Under the first version of the rule it was over a third, because ordinary shipping boilerplate matched.</p></div>
        </div>
      </section>
    </>
  );
}

// Evidence network for the landing hero: branches grow out of the right edge, each ending at a piece of evidence.
// Deterministic (no Math.random) so server and client render the same SVG.
type Branch = { d: string; depth: number; x: number; y: number; trunk: number };

const W = 1400, H = 800, LABELS = ["Price", "Photo", "Wording", "Seller", "Legal basis"];
const r = (n: number) => Math.round(n * 10) / 10;

function grow(x: number, y: number, a: number, len: number, depth: number, trunk: number, n: number, out: Branch[]) {
  const wob = Math.sin(n * 12.9898) * 0.22;
  const ex = x + Math.cos(a + wob) * len, ey = y + Math.sin(a + wob) * len;
  const cx = x + Math.cos(a - wob) * len * 0.55, cy = y + Math.sin(a - wob) * len * 0.55;
  out.push({ d: `M${r(x)} ${r(y)} Q${r(cx)} ${r(cy)} ${r(ex)} ${r(ey)}`, depth, x: ex, y: ey, trunk });
  if (depth >= 4) return;
  const spread = 0.62 - depth * 0.08;
  grow(ex, ey, a - spread, len * 0.74, depth + 1, trunk, n * 2 + 1, out);
  grow(ex, ey, a + spread, len * 0.7, depth + 1, trunk, n * 2 + 2, out);
  if (depth === 1) grow(ex, ey, a + Math.sin(n) * 0.2, len * 0.6, depth + 1, trunk, n * 3 + 5, out);
}
const branches: Branch[] = [];
[-0.95, -0.48, 0, 0.48, 0.95].forEach((da, i) => grow(W, H / 2 + (i - 2) * 24, Math.PI + da, 250, 0, i, i + 1, branches));
const labelled = [0, 1, 2, 3, 4].map((t) => branches.filter((b) => b.depth === 2 && b.trunk === t)[0]);

export function WildlifeSignal() {
  return (
    <svg className="hero-net" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMaxYMid slice" aria-hidden>
      {branches.map((b, i) => <path key={i} d={b.d} pathLength={1} className={`net-line ${b.depth % 2 ? "net-line--teal" : ""}`} style={{ animationDelay: `${b.depth * 420 + (i % 5) * 60}ms` }} />)}
      {branches.filter((b) => b.depth >= 3).map((b, i) => <circle key={i} cx={b.x} cy={b.y} r={b.depth === 4 ? 3.5 : 5} className="net-node" style={{ animationDelay: `${1600 + (i % 9) * 140}ms` }} />)}
      {branches.filter((b, i) => b.depth === 1 && i % 2 === 0).map((b, i) => <path key={i} d={b.d} pathLength={1} className="net-pulse" style={{ animationDelay: `${i * 900}ms` }} />)}
      {labelled.map((b, i) => b && (
        <g key={i} className="net-tag" style={{ animationDelay: `${1300 + i * 260}ms` }}>
          <circle cx={b.x} cy={b.y} r={7} className="net-tag-dot" />
          <rect x={b.x - 6} y={b.y - 40} width={LABELS[i].length * 9.5 + 20} height={26} fill="var(--surface)" stroke="var(--ink)" />
          <text x={b.x + 4} y={b.y - 22} fontSize={14} fontWeight={600} fill="var(--ink)">{LABELS[i]}</text>
        </g>
      ))}
      <circle cx={W} cy={H / 2} r={9} className="net-root" />
    </svg>
  );
}

"use client";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { AGENT_ORDER, AGENTS, STANCE_LABEL } from "@/lib/agents";
import type { Round } from "@/lib/caseState";
import type { Stance } from "@/lib/types";
import { StanceMark } from "./StanceMark";

interface DotProps { cx?: number; cy?: number; payload?: Record<string, unknown>; agent: string; color: string }

// Shape encodes stance (circle file, square dismiss, triangle needs more).
function StanceDot({ cx, cy, payload, agent, color }: DotProps) {
  const stance = payload?.[`${agent}_stance`] as Stance | undefined;
  if (cx === undefined || cy === undefined || !stance) return <g />;
  const r = 5;
  if (stance === "dismiss") return <rect x={cx - r} y={cy - r} width={2 * r} height={2 * r} fill={color} />;
  if (stance === "need_more") return <polygon points={`${cx},${cy - r - 1} ${cx + r + 1},${cy + r} ${cx - r - 1},${cy + r}`} fill={color} />;
  return <circle cx={cx} cy={cy} r={r} fill={color} />;
}

export function ConfidenceChart({ rounds }: { rounds: Round[] }) {
  const data = rounds.map((r) => ({
    round: r.round,
    ...Object.fromEntries(
      AGENT_ORDER.flatMap((a) => (r.posts[a] ? [[a, r.posts[a].confidence], [`${a}_stance`, r.posts[a].stance]] : [])),
    ),
  }));
  const label = rounds.flatMap((r) => AGENT_ORDER.flatMap((a) => (r.posts[a] ? [`${AGENTS[a].label} round ${r.round}: ${STANCE_LABEL[r.posts[a].stance]} ${r.posts[a].confidence}`] : []))).join(". ");

  return (
    <div className="flex h-full items-center gap-4 px-4" role="img" aria-label={`Confidence by round. ${label}`}>
      <div className="flex shrink-0 flex-col gap-1">
        <p className="font-semibold">Confidence</p>
        {AGENT_ORDER.map((a) => (
          <span key={a} className="flex items-center gap-1.5">
            <span className={`size-2 rounded-full ${AGENTS[a].dot}`} />{AGENTS[a].label}
          </span>
        ))}
      </div>
      <div className="h-full min-w-0 flex-1 py-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 16, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="round" type="number" domain={[1, Math.max(2, rounds.length)]} allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} />
            <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} />
            {AGENT_ORDER.map((a) => (
              <Line
                key={a}
                dataKey={a}
                stroke={AGENTS[a].cssVar}
                strokeWidth={2}
                connectNulls
                isAnimationActive={false}
                dot={(p) => <StanceDot key={`${a}-${p.cx}`} cx={p.cx} cy={p.cy} payload={p.payload as Record<string, unknown>} agent={a} color={AGENTS[a].cssVar} />}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex shrink-0 flex-col gap-1 text-muted">
        {(["file", "dismiss", "need_more"] as const).map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <StanceMark stance={s} />
            {STANCE_LABEL[s]}
          </span>
        ))}
      </div>
    </div>
  );
}

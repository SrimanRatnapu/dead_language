import Link from "next/link";
import { WildlifeSignal } from "@/components/WildlifeSignal";
import { AGENTS, AGENT_ORDER } from "@/lib/agents";

const OUTCOMES = [
  { name: "File", tone: "text-red", rule: "All three agree it is illegal." },
  { name: "Contested", tone: "text-amber-ink", rule: "They split. A person decides." },
  { name: "Watchlist", tone: "text-cobalt-ink", rule: "Not enough yet. Checked again later." },
  { name: "Dismiss", tone: "text-green", rule: "All three agree it looks legal." },
];

export default function Landing() {
  return (
    <main className="h-[calc(100dvh-3.5rem)] overflow-y-auto">
      <section className="mx-auto grid min-h-[calc(100dvh-3.5rem)] max-w-7xl items-center gap-10 px-5 py-10 sm:px-8 lg:grid-cols-[1fr_1.2fr]">
        <div className="flex flex-col gap-7">
          <h1 className="serif text-[clamp(2.5rem,5vw,4.5rem)] leading-[1.02] [text-wrap:balance]">
            Coded ivory listings slip past word filters. <span className="text-cobalt-ink">The price and photos give them away.</span>
          </h1>
          <p className="max-w-[52ch] text-xl text-muted">Specialists check each flagged listing&apos;s price, seller, photos and wording. Then three AI agents with opposing goals argue over the evidence, citing a source for every claim. A person approves before anything is reported.</p>
          <Link href="/desk" className="press inline-flex min-h-12 w-fit items-center bg-ink px-7 text-base font-semibold text-bg hover:bg-ink-2">Open the review desk</Link>
        </div>
        <div className="relative w-full lg:-mr-24 lg:justify-self-end">
          <WildlifeSignal />
          <span className="tent lock absolute left-[8%] top-[22%]" style={{ animationDelay: "300ms" }}>Price</span>
          <span className="tent lock absolute right-[8%] top-[18%]" style={{ animationDelay: "600ms" }}>Photo</span>
          <span className="tent lock absolute bottom-[18%] left-[14%]" style={{ animationDelay: "900ms" }}>Wording</span>
        </div>
      </section>

      <section className="border-t border-ink bg-surface">
        <div className="mx-auto grid max-w-7xl gap-12 px-5 py-14 sm:px-8 md:grid-cols-3">
          {AGENT_ORDER.map((a) => (
            <div key={a} className={`reveal border-t-4 pt-4 ${AGENTS[a].ring}`}>
              <h2 className="serif text-3xl">{AGENTS[a].label}</h2>
              <p className="mt-2 text-lg text-muted">{AGENTS[a].goal}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-t border-ink">
        <dl className="mx-auto grid max-w-7xl gap-px px-5 py-14 sm:px-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-10">
          {OUTCOMES.map((o) => (
            <div key={o.name} className="reveal">
              <dt className={`serif text-4xl ${o.tone}`}>{o.name}</dt>
              <dd className="mt-2 text-lg">{o.rule}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}

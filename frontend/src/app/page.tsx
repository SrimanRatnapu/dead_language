import Link from "next/link";
import { WildlifeSignal } from "@/components/WildlifeSignal";
import { AGENTS, AGENT_ORDER } from "@/lib/agents";

const STEPS = [
  { title: "Listing", body: "A flagged listing arrives with its photos, seller and price." },
  { title: "Specialists", body: "Price, seller history, linked sellers, photos and law are checked." },
  { title: "Agents", body: "Three agents with opposing goals argue over the same evidence." },
  { title: "Outcome", body: "Each case ends as likely illegal, contested, watchlist or dismissed." },
];
const OUTCOMES = [
  { name: "Likely illegal", tone: "text-red", dots: ["bg-red", "bg-red", "bg-red"], rule: "All three agree it is illegal." },
  { name: "Contested", tone: "text-amber-ink", dots: ["bg-red", "bg-red", "bg-green"], rule: "They split. Both sides are in the case file." },
  { name: "Watchlist", tone: "text-cobalt-ink", dots: ["bg-sunken ring-1 ring-inset ring-muted", "bg-sunken ring-1 ring-inset ring-muted", "bg-sunken ring-1 ring-inset ring-muted"], rule: "Not enough yet. Checked again later." },
  { name: "Dismiss", tone: "text-green", dots: ["bg-green", "bg-green", "bg-green"], rule: "All three agree it looks legal." },
];

export default function Landing() {
  return (
    <main className="h-[calc(100dvh-3.5rem)] overflow-y-auto">
      <section className="relative isolate min-h-[calc(100dvh-3.5rem)] overflow-hidden">
        <WildlifeSignal />
        <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-7xl items-center px-5 py-10 sm:px-8">
          <div className="flex max-w-[46rem] flex-col gap-7">
            <h1 className="serif text-[clamp(2.25rem,4.4vw,4rem)] leading-[1.05]">
              Three AI agents <span className="text-cobalt-ink">argue every listing.</span>
            </h1>
            <Link href="/desk" className="press inline-flex min-h-12 w-fit items-center bg-ink px-7 text-base font-semibold text-bg hover:bg-ink-2">Open the review desk</Link>
          </div>
        </div>
      </section>

      <section className="border-t border-ink">
        <ol className="mx-auto grid max-w-7xl gap-8 px-5 py-14 sm:px-8 md:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="reveal">
              <div className="step-line mb-4" style={{ transitionDelay: `${i * 80}ms` }} />
              <p className="mono text-muted">{i + 1}</p>
              <h2 className="mt-1 text-xl font-semibold">{s.title}</h2>
              <p className="mt-1 text-muted">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-line">
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
        <dl className="mx-auto grid max-w-7xl gap-10 px-5 py-14 sm:px-8 sm:grid-cols-2 lg:grid-cols-4">
          {OUTCOMES.map((o) => (
            <div key={o.name} className="reveal">
              <div className="mb-4 flex gap-1.5" aria-hidden>{o.dots.map((c, i) => <span key={i} className={`dot-pop size-4 ${c}`} style={{ animationDelay: `${i * 120}ms` }} />)}</div>
              <dt className={`serif text-4xl ${o.tone}`}>{o.name}</dt>
              <dd className="mt-2 text-lg">{o.rule}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}

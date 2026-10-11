import Link from "next/link";
import { WildlifeSignal } from "@/components/WildlifeSignal";
import { AGENTS, AGENT_ORDER } from "@/lib/agents";

const OUTCOMES = [
  { name: "File", tone: "text-red", rule: "All three agents say file.", ask: "You approve it before anything is sent." },
  { name: "Contested", tone: "text-amber-ink", rule: "One says file, another says dismiss.", ask: "You decide, with each side's best argument in front of you." },
  { name: "Watchlist", tone: "text-cobalt-ink", rule: "Something is still open, and no one is arguing file against dismiss.", ask: "It stays listed until something changes." },
  { name: "Dismiss", tone: "text-green", rule: "All three say it looks legal.", ask: "Cleared and logged. No action." },
];

const QUESTIONS: Record<(typeof AGENT_ORDER)[number], string> = {
  undercover: "What is really being sold, and who is it for?",
  counsel: "Is there a lawful origin: an antique, a pre-ban piece, a legal material?",
  case_officer: "Would this hold up, and is it worth a human's week?",
};

const CHAIN = [
  ["Listing frozen", "The text, price and photos are saved as evidence E0, even if the seller removes it."],
  ["Helpers check", "Price, seller history, linked sellers, law and photos. Plain code except the photo and translation steps."],
  ["Agents argue", "Each claim cites evidence IDs. Claims that don't check out are dropped and shown as rejected."],
  ["You approve", "FILE and CONTESTED wait for a named person."],
  ["Report drafted", "A plain-language tip for the enforcement agency, built from validated claims only. Never sent automatically."],
];

export default function Landing() {
  return (
    <main className="h-[calc(100dvh-3.5rem)] overflow-y-auto">
      <section className="mx-auto grid min-h-[calc(100dvh-3.5rem)] max-w-7xl items-center gap-12 px-5 py-12 sm:px-8 lg:grid-cols-[1.05fr_1fr]">
        <div className="flex flex-col gap-7">
          <h1 className="serif max-w-[16ch] text-[clamp(2.75rem,6vw,5.25rem)] font-extrabold leading-[0.98] tracking-[-0.035em] [text-wrap:balance]">
            They can hide the word ivory. They can&rsquo;t hide the price.
          </h1>
          <p className="max-w-[44ch] text-lg text-muted">Three agents with opposing goals review each flagged listing. A person approves anything that gets filed.</p>
          <div className="flex flex-wrap gap-3">
            <Link href="/desk" className="press inline-flex min-h-12 items-center bg-ink px-6 font-semibold text-surface hover:bg-ink-2">Open the review desk</Link>
            <Link href="/results" className="press inline-flex min-h-12 items-center border border-ink px-6 font-semibold hover:bg-surface">Read the audit</Link>
          </div>
        </div>
        <div className="relative justify-self-center lg:justify-self-end">
          <WildlifeSignal />
          <span className="tent lock absolute left-[6%] top-[14%]" style={{ animationDelay: "300ms" }}>Price</span>
          <span className="tent lock absolute right-[8%] top-[24%]" style={{ animationDelay: "600ms" }}>Photo</span>
          <span className="tent lock absolute bottom-[14%] left-[14%]" style={{ animationDelay: "900ms" }}>Wording</span>
        </div>
      </section>

      <section className="border-t border-ink bg-surface">
        <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8">
          <h2 className="serif max-w-[26ch] text-3xl font-bold leading-tight sm:text-4xl">Every review ends one of four ways, and each tells you what to do.</h2>
          <dl className="mt-8 grid border-t border-line sm:grid-cols-2 lg:grid-cols-4">
            {OUTCOMES.map((o) => (
              <div key={o.name} className="border-b border-line py-5 pr-6 lg:border-b-0 lg:border-r lg:last:border-r-0 lg:px-6 lg:first:pl-0">
                <dt className={`serif text-2xl font-bold ${o.tone}`}>{o.name}</dt>
                <dd className="mt-2 text-muted">{o.rule}</dd>
                <dd className="mt-2 font-medium">{o.ask}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_1.3fr]">
        <div>
          <h2 className="serif text-3xl font-bold leading-tight sm:text-4xl">No agent is in charge.</h2>
          <p className="mt-4 max-w-[46ch] text-lg text-muted">Each one owns a question and argues from the same evidence. The outcome comes from a rule written down before any case runs, not from a fourth model.</p>
        </div>
        <ul className="divide-y divide-line border-y border-line">
          {AGENT_ORDER.map((a) => (
            <li key={a} className="grid grid-cols-[auto_1fr] items-baseline gap-x-5 py-5">
              <span className={`serif text-xl font-bold ${AGENTS[a].text}`}>{AGENTS[a].label}</span>
              <span className="text-lg">{QUESTIONS[a]}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="border-y border-ink bg-ink text-surface">
        <div className="relative mx-auto max-w-7xl px-5 py-14 sm:px-8">
          <span className="lattice text-surface/10" aria-hidden />
          <h2 className="serif relative max-w-[24ch] text-3xl font-bold leading-tight sm:text-4xl">Nothing is made up, and nothing leaves without a person.</h2>
          <ol className="relative mt-10 grid gap-y-8 sm:grid-cols-2 lg:grid-cols-5">
            {CHAIN.map(([t, d], i) => (
              <li key={t} className="relative pr-6 lg:border-t lg:border-surface/40 lg:pt-5">
                <span className="tent absolute -top-1 left-0 hidden lg:inline-flex" aria-hidden>{i + 1}</span>
                <h3 className="serif text-xl font-bold lg:mt-3">{t}</h3>
                <p className="mt-2 text-surface/80">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-6 px-5 py-14 sm:px-8">
        <p className="serif max-w-[30ch] text-2xl font-bold leading-snug">Start with a recorded review, or fetch live listings and watch the queue fill.</p>
        <Link href="/desk" className="press inline-flex min-h-12 items-center bg-amber px-6 font-semibold text-ink hover:brightness-95">Open the review desk</Link>
      </section>
    </main>
  );
}

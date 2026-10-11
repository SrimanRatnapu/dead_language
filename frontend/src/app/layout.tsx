import type { Metadata } from "next";
import { APP_NAME } from "@/lib/agents";
import { Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const sans = Hanken_Grotesk({ variable: "--font-sans", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Three agents review coded wildlife listings so honest sellers aren't flagged and real ivory isn't missed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="glass sticky top-0 z-20 flex h-14 shrink-0 items-center border-b border-line/80 px-5 sm:px-8">
          <Link href="/" className="group flex items-center gap-2.5" aria-label={`${APP_NAME} home`}>
            <span className="grid size-7 place-items-center border border-cobalt/60 text-xs font-bold text-cobalt transition-transform duration-200 group-hover:rotate-12">DL</span>
            <span className="hidden font-semibold tracking-[-0.04em] sm:inline">{APP_NAME}</span>
          </Link>
          <nav className="ml-auto flex items-center text-sm sm:gap-1" aria-label="Primary navigation">
            <Link href="/" className="press rounded-md inline-flex min-h-11 items-center px-2 sm:px-3 text-muted hover:bg-surface hover:text-ink">Listings</Link>
            <Link href="/pipeline" className="press rounded-md inline-flex min-h-11 items-center px-2 sm:px-3 text-muted hover:bg-surface hover:text-ink">Pipeline</Link>
            <Link href="/metrics" className="press rounded-md inline-flex min-h-11 items-center px-2 sm:px-3 text-muted hover:bg-surface hover:text-ink">Metrics</Link>
            <Link href="/replays" className="press rounded-md inline-flex min-h-11 items-center px-2 sm:px-3 text-muted hover:bg-surface hover:text-ink">Replays</Link>
            <Link href="/results" className="press rounded-md inline-flex min-h-11 items-center px-2 sm:px-3 text-muted hover:bg-surface hover:text-ink">Evaluation</Link>
          </nav>
        </header>
        <div className="min-h-0 flex-1" role="presentation">{children}</div>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono, Instrument_Serif } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const sans = Hanken_Grotesk({ variable: "--font-sans", subsets: ["latin"] });
const serif = Instrument_Serif({ variable: "--font-serif", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dead Language",
  description: "Three agents review coded wildlife listings so honest sellers aren't flagged and real ivory isn't missed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="glass sticky top-0 z-20 flex h-12 shrink-0 items-center gap-6 px-6">
          <Link href="/" className="display text-2xl italic">Dead Language</Link>
          <nav className="ml-auto flex gap-5 text-muted">
            <Link href="/" className="hover:text-ink">Demo</Link>
            <Link href="/results" className="hover:text-ink">Results</Link>
          </nav>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </body>
    </html>
  );
}

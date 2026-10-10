import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono, Newsreader } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const sans = Hanken_Grotesk({ variable: "--font-sans", subsets: ["latin"] });
const serif = Newsreader({ variable: "--font-serif", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dead Language",
  description: "Three agents review coded wildlife listings so honest sellers aren't flagged and real ivory isn't missed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="glass sticky top-0 z-20 flex h-12 shrink-0 items-center gap-6 border-b border-line px-5">
          <Link href="/" className="display text-lg">Dead Language</Link>
          <nav className="flex gap-4 text-muted">
            <Link href="/" className="hover:text-ink">Listings</Link>
            <Link href="/results" className="hover:text-ink">Results</Link>
          </nav>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </body>
    </html>
  );
}

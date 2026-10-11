import type { Metadata } from "next";
import { APP_NAME } from "@/lib/agents";
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { NavLinks } from "@/components/NavLinks";
import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const display = Bricolage_Grotesque({ variable: "--font-display", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Three agents with opposing goals review coded wildlife listings. A person approves anything that is filed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${display.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="glass sticky top-0 z-20 flex h-14 shrink-0 items-center px-5 sm:px-8">
          <Link href="/" className="flex items-center gap-3" aria-label={`${APP_NAME} home`}>
            <span className="tent">DL</span>
            <span className="serif hidden text-lg font-bold sm:inline">{APP_NAME}</span>
          </Link>
          <Suspense fallback={null}><NavLinks /></Suspense>
          <span className="lattice text-surface/30" style={{ inset: "auto 0 0 0", height: 6 }} aria-hidden />
        </header>
        <div className="min-h-0 flex-1" role="presentation">{children}</div>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { APP_NAME } from "@/lib/agents";
import { Instrument_Serif, Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { NavLinks } from "@/components/NavLinks";
import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const display = Instrument_Serif({ variable: "--font-display", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });
const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Three agents with opposing goals review coded wildlife listings. A person approves anything that is filed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${display.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center border-b border-line bg-bg px-5 sm:px-8">
          <Link href="/" className="serif text-2xl leading-none" aria-label={`${APP_NAME} home`}>{APP_NAME}</Link>
          <Suspense fallback={null}><NavLinks /></Suspense>
        </header>
        <div className="min-h-0 flex-1" role="presentation">{children}</div>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { APP_NAME } from "@/lib/agents";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { NavLinks } from "@/components/NavLinks";
import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Three agents review flagged wildlife listings.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full`}>
      <body className="flex h-full flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center border-b border-line bg-bg px-5 sm:px-8">
          <Link href="/" className="serif text-3xl leading-none" aria-label={`${APP_NAME} home`}>{APP_NAME}</Link>
          <Suspense fallback={null}><NavLinks /></Suspense>
        </header>
        <div className="min-h-0 flex-1" role="presentation">{children}</div>
      </body>
    </html>
  );
}

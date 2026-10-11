"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/desk", label: "Review desk", active: (p: string) => p.startsWith("/desk") || p.startsWith("/case") || p.startsWith("/listing") || p.startsWith("/replay") },
  { href: "/results", label: "Audit", active: (p: string) => p.startsWith("/results") },
];

export function NavLinks() {
  const path = usePathname();
  return (
    <nav className="ml-auto flex h-full items-stretch gap-1 text-sm sm:gap-3" aria-label="Primary navigation">
      {LINKS.map((l) => {
        const on = l.active(path);
        return (
          <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
            className={`relative inline-flex items-center px-2 font-medium transition-colors after:absolute after:inset-x-2 after:bottom-1.5 after:h-0.5 after:transition-colors sm:px-3 ${on ? "text-surface after:bg-amber" : "text-surface/70 hover:text-surface hover:after:bg-surface/40"}`}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

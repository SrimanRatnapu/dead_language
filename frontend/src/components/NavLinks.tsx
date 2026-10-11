"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Cases", active: (p: string) => !p.startsWith("/results") },
  { href: "/results", label: "Results", active: (p: string) => p.startsWith("/results") },
];

export function NavLinks() {
  const path = usePathname();
  return (
    <nav className="ml-auto flex h-full items-stretch gap-1 text-sm sm:gap-3" aria-label="Primary navigation">
      {LINKS.map((l) => {
        const on = l.active(path);
        return (
          <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
            className={`relative inline-flex items-center px-2 font-medium transition-colors after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:transition-colors sm:px-3 ${on ? "text-ink after:bg-cobalt" : "text-muted hover:text-ink hover:after:bg-line"}`}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

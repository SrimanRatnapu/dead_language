import type { Capability } from "@/lib/types";

// One stroke weight, one 24px grid, authored here so no icon dependency is needed.
const PATHS = {
  listing_snapshot: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7",
  price_check: "M3 12V4h8l10 10-8 8zM8 8h.01",
  seller_inventory: "M4 8l2-4h12l2 4M4 8v12h16V8M4 8h16M9 13h6",
  linked_sellers: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
  legal_lookup: "M12 3v18M5 7h14M5 7l-3 8a3 3 0 0 0 6 0zM19 7l-3 8a3 3 0 0 0 6 0zM8 21h8",
  material_exam: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  translation: "M4 5h9M8 3v2M6 5c0 4 3 7 6 8M12 5c0 4-3 7-7 8M13 21l4-10 4 10M14.5 18h5",
  system_notice: "M12 8v5M12 16.5h.01M10.3 4l-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12l5 5 9-10",
  play: "M7 5l12 7-12 7z",
  pause: "M8 5v14M16 5v14",
  skip: "M5 5l9 7-9 7zM18 5v14",
  chevron: "M9 6l6 6-6 6",
  flag: "M6 21V4M6 4h11l-2 4 2 4H6",
  split: "M12 3v18M12 3a9 9 0 0 0 0 18",
  contested: "M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className }: { name: IconName | Capability; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  );
}

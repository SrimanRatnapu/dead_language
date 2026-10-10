"use client";
import Link from "next/link";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { ListingRow } from "@/lib/types";
import { Photo } from "./Photo";

export function ListingCard({ row }: { row: ListingRow }) {
  const { listing } = row;
  return (
    <Link href={`/listing/${listing.id}`} className="press group min-w-0">
      <div className="overflow-hidden border border-line bg-surface">
        <Photo src={imageUrl(listing.image_paths[0] ?? "")} label={listing.title} className="aspect-[4/3] w-full transition duration-500 group-hover:scale-[1.04]" />
      </div>
      <span className="mt-3 line-clamp-2 block font-semibold leading-snug">{listing.title}</span>
      <span className="mt-1 block text-lg font-semibold tracking-tight text-cobalt-ink">{usd(listing.price_usd)}</span>
    </Link>
  );
}

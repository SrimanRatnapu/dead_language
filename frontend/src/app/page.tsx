"use client";
import { useEffect, useState } from "react";
import { ListingCard } from "@/components/ListingCard";
import { loadListings } from "@/lib/stubs";
import type { ListingRow } from "@/lib/types";

export default function Listings() {
  const [rows, setRows] = useState<ListingRow[] | null>(null);
  useEffect(() => { loadListings().then(({ data }) => setRows(data)).catch(() => setRows([])); }, []);
  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <h1 className="text-xl font-semibold tracking-tight">Listings</h1>
        <p className="mt-3 max-w-xl text-base text-muted">Open any listing to read it, then run a review on it.</p>
        {rows === null ? <p className="mt-10 text-muted">Loading listings…</p>
          : rows.length === 0 ? <p className="mt-10 text-muted">No listings found.</p>
          : <div className="mt-8 grid gap-x-5 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">{rows.map((row) => <ListingCard key={row.listing.id} row={row} />)}</div>}
      </div>
    </main>
  );
}

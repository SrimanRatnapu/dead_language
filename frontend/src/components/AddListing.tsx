"use client";
import { useRef, useState } from "react";
import { addToQueue } from "@/lib/api";

type Added = Awaited<ReturnType<typeof addToQueue>>;

/** Button + modal: paste an eBay link, item number or listing id and the agents start on it. */
export function AddListing({ onAdded }: { onAdded: (r: Added) => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onAdded(await addToQueue(ref.trim())); setRef(""); dlg.current?.close(); }
    catch (err) { setError(err instanceof Error ? err.message : "That did not work."); }
    finally { setBusy(false); }
  }
  return <>
    <button onClick={() => { setError(null); dlg.current?.showModal(); }} className="press min-h-11 border border-ink px-4 py-2.5 font-semibold hover:bg-surface">Add a listing</button>
    <dialog ref={dlg} onClick={(e) => { if (e.target === dlg.current) dlg.current?.close(); }} aria-labelledby="add-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] border border-ink bg-bg p-6 text-ink backdrop:bg-ink/40">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <h2 id="add-title" className="text-xl font-semibold">Add a listing</h2>
        <label className="text-sm text-muted">eBay link, item number or listing ID
          <input value={ref} onChange={(e) => setRef(e.target.value)} autoFocus placeholder="https://www.ebay.com/itm/…" className="mt-1 block min-h-11 w-full border border-line bg-surface px-3 text-base text-ink" /></label>
        {error && <p role="alert" className="text-red">{error}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => dlg.current?.close()} className="press min-h-11 px-4 py-2.5 font-semibold hover:bg-surface">Cancel</button>
          <button type="submit" disabled={busy || !ref.trim()} className="press min-h-11 bg-ink px-4 py-2.5 font-semibold text-surface hover:bg-ink-2 disabled:opacity-40">{busy ? "Adding…" : "Add and review"}</button>
        </div>
      </form>
    </dialog>
  </>;
}

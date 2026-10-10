// Ids come from data/demo_cases.json; replays from fixtures/replays (copied to public/replays).
// The current replays are scripted (scripts/record_scripted_demo.py); the UI detects that from their
// "DEMO-" case ids, so recorded live runs dropped in under the same names lose the notice automatically.
export const DEMO_CASES = [
  { key: "D1", label: "Network case", listingId: "L0266", replay: "d1_network",
    blurb: "A \u201cbone\u201d netsuke at 12x the going price, and the same photo under a second seller." },
  { key: "D2", label: "Tagua case", listingId: "L0181", replay: "d2_tagua",
    blurb: "A $20 tagua nut carving. The review clears an honest seller." },
  { key: "D3", label: "Removed listing", listingId: "L0241", replay: "d3_removed",
    blurb: "The seller pulls the listing mid-review. It comes back under a new account." },
  { key: "D4", label: "Ambiguous case", listingId: "L0172", replay: "d4_ambiguous",
    blurb: "High price, one blurry photo. The agents disagree, so a person decides." },
] as const;

export const demoCaseForReplay = (name: string) => DEMO_CASES.find((c) => c.replay === name);
export const demoCaseForListing = (id: string) => DEMO_CASES.find((c) => c.listingId === id);

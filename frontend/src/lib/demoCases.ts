// Ids come from data/demo_cases.json; replays from fixtures/replays (copied to public/replays).
// `scripted: true` = produced by scripts/record_scripted_demo.py: the real pipeline ran, but the agents'
// wording and the photo readings were written by hand. Set it to false once a live run is recorded.
export const DEMO_CASES = [
  { key: "D1", label: "Network case", listingId: "L0266", replay: "d1_network", scripted: true,
    blurb: "A \u201cbone\u201d netsuke at 12x the going price, and the same photo under a second seller." },
  { key: "D2", label: "Tagua case", listingId: "L0181", replay: "d2_tagua", scripted: true,
    blurb: "A $20 tagua nut carving. The review clears an honest seller." },
  { key: "D3", label: "Removed listing", listingId: "L0241", replay: "d3_removed", scripted: true,
    blurb: "The seller pulls the listing mid-review. It comes back under a new account." },
  { key: "D4", label: "Ambiguous case", listingId: "L0172", replay: "d4_ambiguous", scripted: true,
    blurb: "High price, one blurry photo. The agents disagree, so a person decides." },
] as const;

export const demoCaseForReplay = (name: string) => DEMO_CASES.find((c) => c.replay === name);
export const demoCaseForListing = (id: string) => DEMO_CASES.find((c) => c.listingId === id);

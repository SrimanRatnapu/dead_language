// Ids come from data/demo_cases.json. `replay` stays on sample_case until Task 10 records
// fixtures/replays/d{1,2,3}_*.jsonl; then copy them to public/replays and rename here.
export const DEMO_CASES = [
  { key: "D1", label: "Network case", listingId: "L0266", replay: "sample_case" },
  { key: "D2", label: "Tagua case", listingId: "L0181", replay: "sample_case" },
  { key: "D3", label: "Removed listing", listingId: "L0241", replay: "sample_case" },
] as const;

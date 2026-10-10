// Run: npm test  (plain node, no framework)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { initialCaseState, reduce } from "../src/lib/caseState.ts";

const events = readFileSync(new URL("../../fixtures/sample_case_events.jsonl", import.meta.url), "utf8")
  .split("\n").filter(Boolean).map((l) => JSON.parse(l));
const s = events.reduce(reduce, initialCaseState);

assert.equal(s.rounds.length, 2);
assert.equal(Object.keys(s.rounds[1].posts).length, 3);
assert.equal(s.caseFile?.outcome, "FILE");
assert.equal(s.evidenceOrder.length, events.filter((e) => e.type === "evidence.added").length);
assert.equal(s.rounds[0].rejected.length, 1);
// feed keeps arrival order: first item is evidence, last post comes after the second round marker
assert.equal(s.feed[0].kind, "evidence");
assert.equal(s.feed.filter((f) => f.kind === "post").length, 6);
// replayed events (reconnect) are ignored
assert.deepEqual(events.reduce(reduce, s), s);
console.log("caseState ok");

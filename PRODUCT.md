# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: Trust & Safety analyst at an online marketplace (eBay-type). Works a review queue of listings that might be coded ivory sales, on a desktop, in long sessions. Job: clear the queue, approve or reject each filing, never accuse an honest seller. Their name goes on every approval.
Secondary: wildlife enforcement investigator (USFWS, state Fish & Wildlife, customs) who receives a filed case and needs the evidence, legal basis and drafted tip. NGO / coalition researcher (Coalition to End Wildlife Trafficking Online, TRAFFIC-type) who reads outcomes and patterns across batches.
Audience for the hackathon demo (Cisco/AGNTCY judges) sees the same product; the UI must be demoable without becoming a different product. [Inferred from docs/specs/00-dead-language-design-spec.md and v2 plans; primary user confirmed by the team.]

## Product Purpose
Coded wildlife listings fool word filters but not the price or photos. For each suspicious listing, three agents with competing goals (Undercover, Counsel, Case Officer) review one evidence board and cite evidence IDs for every claim. Outcomes are FILE, DISMISS, CONTESTED or WATCHLIST by a published rule. A human approves before anything is sent. Success: a short, trustworthy queue of decisions for a human, with the disagreement preserved and every claim traceable.

## Positioning
The disagreement is kept, not averaged away: CONTESTED goes to a human with each side's best argument. Every claim cites evidence; click it and see the raw source. Nothing is sent without human approval.

## Constraints and facts
- Language rule: never courtroom words (court, trial, verdict, jury, judge, prosecutor, guilty). Use case review, outcome, agents, evidence, positions. Live-lane results say "flagged for human review", never "illegal".
- No auth, no auto-submission of tips. Reconstructed trafficking cases are labelled as reconstructed; use only measured numbers.
- App name undecided; lives in `APP_NAME` (frontend/src/lib/agents.ts).
- Accessibility: contrast AA, keyboard reachable, reduced-motion respected.

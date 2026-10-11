# Watchdog — 3-minute pitch (draft)

About 440 spoken words, roughly 3:00 at a calm pace. Timings are targets.
Numbers come from spec §14 sources, `results/examiner_eval.json` and `results/load_test.json`.

---

## 0:00 — Why us (Sriman)

I volunteered at a zoo for three years. Wildlife is my passion, and it's why most of what I build ends up combining AI and animals: I've done several projects on that, from monitoring enclosures to using language models to read animal behavior.

This weekend we pointed that at something uglier.

## 0:25 — The problem

Researchers counted about 266,000 wildlife products for sale across 61 online marketplaces in two years. eBay banned ivory in 2009. A University of Kent study still found real ivory listed as "bone", and a month after it was reported, under 7% had been taken down.

Keyword filters fail because sellers simply stop using the word.

## 0:50 — The insight

But a coded listing has two readers: the filter and the buyer. It has to fool one and still convince the other.

So the signal is always where the buyer can see it. A "bone" carving priced like ivory. A close-up of the base showing ivory grain.

**They can hide the word ivory. They can't hide the price.**

## 1:10 — What we built (switch to the demo)

Watchdog reviews each suspicious listing with three AI agents that want different things, and nobody is in charge.

- **Undercover** reads the listing like a collector would: what is really being sold?
- **Counsel** builds the strongest innocent explanation, to protect honest sellers.
- **Case Officer** asks whether this is worth an investigator's week.

Neutral specialists, mostly plain code, put facts on a shared evidence board: price against the market, the seller's other items, linked sellers, the law, and a photo exam.

Watch this one. A "bone" netsuke at an ivory price. Round one, they split. Counsel asks for a closer photo exam, it comes back ivory grain, and Counsel changes position and cites that evidence. Case Officer asks for linked sellers and finds a network sharing wording and a reused photo. Outcome: file, for a human to approve.

And this tagua nut carving at a normal price? Dismissed. It clears honest sellers too.

## 2:15 — Why you can trust it

Every claim must cite evidence, and code checks the numbers and quotes. Click any claim: nothing is made up.

On 41 labeled museum photos, our photo examiner was right on all 28 it was willing to call, and said "cannot tell" on the rest. It caught 16 of 20 ivory pieces with zero false ivory calls.

A full three-agent review costs about 17 cents a case.

And nothing is ever sent automatically. A named human approves every report.

## 2:45 — Close

Agents that disagree, so real ivory doesn't get missed and honest sellers don't get flagged.

Every accusation gets a defender. Thank you.

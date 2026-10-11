# Design

Security-print world built on the Schreger-line crosshatch that identifies ivory. Documents, serials and evidence tents, not dashboards.

## Color
- Ground `--bg` oklch(.962 .007 200) cool mineral, never cream. Surface `--surface`, sunken `--sunken`, hairlines `--line`.
- Ink `--ink` oklch(.2 .035 205): text, primary buttons, the nav bar.
- One brand accent: marker yellow `--amber` oklch(.87 .17 95), used for evidence tents, the active nav underline, the landing close CTA.
- Outcome inks (semantic only): FILE `--red`, DISMISS `--green`, WATCHLIST `--cobalt` (steel), CONTESTED `--amber-ink`. Agents keep amber (Undercover), teal (Counsel), violet (Case Officer).

## Type
Bricolage Grotesque for display (`.serif` utility, weight 700-800, tracking -0.03em). Geist for UI. Geist Mono for serials and evidence ids (`.serial`, `.tent`).

## Shape and depth
All corners sharp. Elevation is a hairline border or a rule, never both with a shadow. Rules in ink weight divide sections; lines in `--line` divide rows.

## Signature pieces
- `.lattice`: empty element, mask of crossing sine waves, colour from currentColor. Only on plates, the nav base, the empty desk. Never behind text.
- `.tent`: chamfered yellow tag for evidence ids and signal labels (EvidenceChip, landing hero).
- `WildlifeSignal`: the animated evidence network (orbits, leaves, pulsing core) on the landing hero.

## Surfaces
Landing `/` (Persuade), Review desk `/desk` (Operate: inbox grouped by required action), Case `/case/*`, Listing `/listing/*`, Replay, Audit `/results` (Read).

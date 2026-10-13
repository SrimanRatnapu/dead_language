# Watchdog

Wildlife traffickers rarely write "ivory". They write "old bone carving", "mammoth-style", "vintage piano key". Keyword filters miss it.

Watchdog reads flagged marketplace listings the way an investigator would. Specialists check the price, seller, photos and wording. Then three AI agents with opposing goals argue over the evidence, and every claim has to cite a source:

- **Undercover** looks for red flags.
- **Counsel** looks for innocent explanations.
- **Case officer** compares against past cases.

They end on one of four outcomes: likely illegal, contested, watching, or dismissed. Each comes with a case file.

**1st place, Cisco track (When AI Agents Disagree), UCSC AI Hackathon.**

[Demo video](https://youtu.be/Vn_vT54s7Kw)

## Run it

```
cp .env.example .env     # add ANTHROPIC_API_KEY
cd backend && uv run uvicorn deadlang.api.server:app --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. Backend tests: `cd backend && uv run pytest -q -m "not integration"`.

"""Material Examiners (plan 03 Task 8): look at listing photos and report the apparent material.

Two examiners offer the same capability so the demo can show a fallback: thorough (strong model, two
independent runs that must agree) is preferred; quick (fast model, one run, confidence capped) is the fallback.
The model sees only the photos, never the title, description or price.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from deadlang import config, llm
from deadlang.llm import BudgetExceeded
from deadlang.schemas import EvidenceDraft, SpecialistCall, SpecialistReply

MATERIALS = ["elephant_ivory", "bone", "resin_or_plastic", "tagua_nut", "wood", "other", "cannot_tell"]
MAX_PHOTOS = 3
QUICK_CONFIDENCE_CAP = 0.6
SCHEMA_NAME = "report_material"
USER_MESSAGE = "Photos are numbered in the order given, starting at 0. Return one entry per photo."
SECOND_LOOK_NOTE = "Examine bases and cut surfaces first."
PROMPT_FILE = Path(__file__).parent / "prompts" / "material_exam.md"

SCHEMA = {
    "type": "object",
    "properties": {"photos": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "material": {"type": "string", "enum": MATERIALS},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "visible_features": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "best_region": {"type": "string"},
        },
        "required": ["index", "material", "confidence", "visible_features", "best_region"],
    }}},
    "required": ["photos"],
}


def _normalise(out: dict, count: int) -> list[dict]:
    """One clean entry per photo position 0..count-1, whatever the model returned."""
    by_index: dict[int, dict] = {}
    for entry in out.get("photos") or []:
        idx = entry.get("index") if isinstance(entry, dict) else None
        if isinstance(idx, int) and 0 <= idx < count and idx not in by_index:
            by_index[idx] = entry
    clean = []
    for i in range(count):
        e = by_index.get(i, {})
        mat = e.get("material")
        known = mat in MATERIALS
        try:
            conf = min(max(float(e.get("confidence", 0.0)), 0.0), 1.0) if known else 0.0
        except (TypeError, ValueError):
            conf = 0.0
        feats = [str(f) for f in (e.get("visible_features") or [])][:3]
        clean.append({"material": mat if known else "cannot_tell", "confidence": conf,
                      "visible_features": feats, "best_region": str(e.get("best_region") or "")})
    return clean


def _merge_features(a: list[str], b: list[str]) -> list[str]:
    return (a + [f for f in b if f not in a])[:3]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class _Examiner:
    capability = "material_exam"
    name: str
    tier: str
    mode: str

    def __init__(self, market: Any, model: str):
        self.market = market
        self.model = model
        self.system = PROMPT_FILE.read_text(encoding="utf-8")

    # ---- model calls ----

    async def _look(self, image_paths: list[Path], case_id: str | None, temperature: float,
                    user: str = USER_MESSAGE) -> list[dict]:
        out = await llm.call_vision_json(
            model=self.model, system=self.system, user=user, image_paths=image_paths,
            schema_name=SCHEMA_NAME, schema=SCHEMA, case_id=case_id, temperature=temperature)
        return _normalise(out, len(image_paths))

    async def _runs(self, image_paths: list[Path], case_id: str | None) -> list[list[dict]]:
        raise NotImplementedError

    async def examine(self, image_paths: list[Path], case_id: str | None,
                      indices: list[int] | None = None) -> list[dict]:
        """Per-photo results, reported under `indices` (default 0..n-1). Also used by the accuracy test."""
        indices = indices if indices is not None else list(range(len(image_paths)))
        runs = await self._runs(image_paths, case_id)
        photos = []
        for pos, index in enumerate(indices):
            photo = self._combine([run[pos] for run in runs])
            photos.append({"index": index, **photo, "confidence": round(photo["confidence"], 1)})
        return photos

    def _combine(self, per_run: list[dict]) -> dict:
        raise NotImplementedError

    # ---- specialist ----

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        listing = await self.market.get_listing_snapshot(call.listing_id)
        if not listing.image_paths:
            return SpecialistReply(ok=False, error="no_images")
        raw_index = call.params.get("image_index")
        if raw_index is None:
            indices = list(range(min(MAX_PHOTOS, len(listing.image_paths))))
        else:
            try:
                idx = int(raw_index)
            except (TypeError, ValueError):
                return SpecialistReply(ok=False, error="bad_image_index")
            if not 0 <= idx < len(listing.image_paths):
                return SpecialistReply(ok=False, error="image_index_out_of_range")
            indices = [idx]
        paths = [self.market.image_path(listing.image_paths[i]) for i in indices]
        try:
            photos = await self.examine(paths, call.case_id, indices)
        except BudgetExceeded:
            return SpecialistReply(ok=False, error="budget")
        return SpecialistReply(ok=True, drafts=[self._draft(listing.id, photos)])

    def _draft(self, listing_id: str, photos: list[dict]) -> EvidenceDraft:
        decisive = [p for p in photos if p["material"] != "cannot_tell"]
        best = max(decisive, key=lambda p: p["confidence"]) if decisive else None
        others = len(photos) - 1 if best else 0
        others_unsure = sum(1 for p in photos if p is not best and p["material"] == "cannot_tell") if best else 0
        data = {"listing_id": listing_id, "mode": self.mode, "model": self.model, "photos": photos,
                "overall": best["material"] if best else "cannot_tell",
                "n_photos": len(photos), "decisive_photos": len(decisive),
                "best_photo": best["index"] if best else None,
                "other_photos": others, "other_cannot_tell": others_unsure}
        if best is None:
            return EvidenceDraft(capability="material_exam", summary=self._unsure_summary(len(photos)), data=data,
                                 produced_by="model", confidence=0.0, specialist_name=self.name)
        feature = best["visible_features"][0] if best["visible_features"] else "visible features"
        summary = (f"Photo {best['index']} shows {feature} consistent with {best['material'].replace('_', ' ')} "
                   f"(confidence {best['confidence']:.1f})")
        if others and others_unsure == others:
            summary += f"; {_plural(others, 'other photo')}: cannot tell."
        elif others:
            summary += f"; {_plural(others, 'other photo')}: {others_unsure} cannot tell."
        else:
            summary += "."
        return EvidenceDraft(capability="material_exam", summary=summary, data=data, produced_by="model",
                             confidence=best["confidence"], specialist_name=self.name)

    def _unsure_summary(self, n: int) -> str:
        raise NotImplementedError


class ThoroughExaminer(_Examiner):
    """Two independent looks; a material is reported only when both agree."""
    name = "deadlang-examiner-thorough"
    tier = "preferred"
    mode = "thorough"

    def __init__(self, market: Any):
        super().__init__(market, config.MODEL_STRONG)

    async def _runs(self, image_paths: list[Path], case_id: str | None) -> list[list[dict]]:
        # Newer models ignore temperature, so the second look is made different on purpose: the photos in
        # reverse order and a note to start with bases and cut surfaces. (Temperature still helps on models
        # that accept it.) Both looks run at the same time and share one encode of each photo.
        results = await asyncio.gather(
            self._look(image_paths, case_id, 0.7),
            self._look(list(reversed(image_paths)), case_id, 0.7, user=f"{USER_MESSAGE} {SECOND_LOOK_NOTE}"),
            return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                raise r
        first, second = results
        return [first, second[::-1]]          # the second look's entries go back to the original photo order

    def _combine(self, per_run: list[dict]) -> dict:
        a, b = per_run
        features = _merge_features(a["visible_features"], b["visible_features"])
        region = a["best_region"] or b["best_region"]
        if a["material"] == b["material"] != "cannot_tell":
            return {"material": a["material"], "confidence": min(a["confidence"], b["confidence"]),
                    "visible_features": features, "best_region": region}
        return {"material": "cannot_tell", "confidence": 0.0, "visible_features": features, "best_region": region}

    def _unsure_summary(self, n: int) -> str:
        return (f"The examiner could not tell the material from the {_plural(n, 'photo')} "
                "(thorough mode: the two runs disagreed or both were unsure).")


class QuickExaminer(_Examiner):
    """One look with the fast model; confidence never above 0.6."""
    name = "deadlang-examiner-quick"
    tier = "fallback"
    mode = "quick"

    def __init__(self, market: Any):
        super().__init__(market, config.MODEL_FAST)

    async def _runs(self, image_paths: list[Path], case_id: str | None) -> list[list[dict]]:
        return [await self._look(image_paths, case_id, 0.0)]

    def _combine(self, per_run: list[dict]) -> dict:
        (only,) = per_run
        return {**only, "confidence": min(only["confidence"], QUICK_CONFIDENCE_CAP)}

    def _unsure_summary(self, n: int) -> str:
        return (f"The examiner could not tell the material from the {_plural(n, 'photo')} "
                "(quick mode: the single run was unsure).")

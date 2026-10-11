"""Which model each role runs on (v2 plan B4). Cheap model: triage and translation (DL_MODEL_TRIAGE, which defaults
to DL_MODEL_FAST) and the quick examiner fallback. Strong model (DL_MODEL_STRONG): the thorough examiner and every
deliberating agent. Anything that can lead to an accusation does not run on the cheap model."""
import pytest

from deadlang import config, llm, triage
from deadlang.deliberation.agents import DeliberatingAgent
from deadlang.deliberation.facilitator import AGENTS
from deadlang.eval import baselines
from deadlang.schemas import DeliberationTurn
from deadlang.specialists.language import Translator
from deadlang.specialists.material import QuickExaminer, ThoroughExaminer
from tests.fakes import make_listing


@pytest.fixture
def models(monkeypatch):
    """Three clearly different model names, so a role wired to the wrong one cannot pass by accident."""
    monkeypatch.setattr(config, "MODEL_STRONG", "strong-model")
    monkeypatch.setattr(config, "MODEL_FAST", "fast-model")
    monkeypatch.setattr(config, "MODEL_TRIAGE", "triage-model")


class Recorder:
    def __init__(self):
        self.models = []

    async def __call__(self, **kw):
        self.models.append(kw["model"])
        return {"stance": "need_more", "confidence": 0.5, "claims": [], "decision": "dismiss", "reason": "r",
                "score": 0.1, "suspicious": False, "title_en": "t", "description_en": "d", "notable_phrases": []}


def turn():
    return DeliberationTurn(case_id="C-1", round=1, max_rounds=4, evidence=[], transcript=[])


@pytest.mark.parametrize("role", list(AGENTS))
async def test_every_deliberating_agent_runs_on_the_strong_model(models, monkeypatch, role):
    rec = Recorder()
    monkeypatch.setattr(llm, "call_json", rec)
    await DeliberatingAgent(role).handle(turn())
    assert rec.models == ["strong-model"]


async def test_triage_runs_on_the_triage_model(models, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(llm, "call_json", rec)
    await triage.screen(make_listing(), None)
    assert rec.models == ["triage-model"]


def test_translation_runs_on_the_triage_model(models):
    assert Translator(object()).model == "triage-model"


def test_the_thorough_examiner_is_strong_and_the_quick_fallback_is_fast(models):
    assert ThoroughExaminer(object()).model == "strong-model"
    assert QuickExaminer(object()).model == "fast-model"


async def test_the_evaluation_baselines_use_the_strong_model_too(models, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(llm, "call_json", rec)
    await baselines.listing_only(make_listing(), "x")
    assert rec.models == ["strong-model"]


def _defaults(code: str) -> str:
    """config values with no DL_* settings in the environment (and none from .env, which only fills gaps)."""
    import os, subprocess, sys
    from pathlib import Path
    env = {k: v for k, v in os.environ.items() if not k.startswith("DL_")}
    env.update({"DL_MODEL_STRONG": "", "DL_MODEL_FAST": "", "DL_MODEL_TRIAGE": ""})       # empty means: use the default
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", f"from deadlang import config; print({code})"],
                         cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def test_the_built_in_defaults_put_no_accusing_role_on_the_cheap_model():
    assert _defaults("config.MODEL_TRIAGE == config.MODEL_FAST") == "True"                # the documented default
    assert _defaults("'haiku' in config.MODEL_FAST and 'haiku' not in config.MODEL_STRONG") == "True"

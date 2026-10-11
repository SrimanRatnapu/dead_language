"""The Case Officer gate must name a role that really exists, using the roster constants rather than string
literals. This is the bug the agent rename (buyer/defender/caseload -> undercover/counsel/case_officer) nearly
caused: the gate still said "caseload", which merged without a conflict and would have silently never fired."""
import inspect
import re
from pathlib import Path
from typing import get_args

import pytest

from deadlang.agntcy.cards import ALL_AGENT_NAMES, DELIBERATOR_NAMES, card_for
from deadlang.deliberation import casefile, crosscase, rules
from deadlang.deliberation import facilitator as facilitator_module
from deadlang.deliberation.agents import PROMPTS, DeliberatingAgent
from deadlang.deliberation.facilitator import AGENTS, Facilitator
from deadlang.schemas import AgentName, Requester

OLD_NAMES = ("buyer", "defender", "caseload")


def test_the_gate_names_a_role_that_is_on_the_real_roster():
    role = crosscase.CROSS_CASE_ROLE
    assert role in get_args(AgentName)                      # the schema's own list of roles
    assert role in AGENTS                                   # the Facilitator's roster
    assert role in casefile.ORDER                           # the case file's ordering
    assert role in DELIBERATOR_NAMES                        # an agent card and a SLIM identity exist for it
    assert DELIBERATOR_NAMES[role] in ALL_AGENT_NAMES
    assert card_for(DELIBERATOR_NAMES[role]).skills[0].id == "deliberate"
    assert (PROMPTS / f"{role}.md").is_file()               # and a prompt
    assert DeliberatingAgent(role).name == role             # and it can be built


def test_every_roster_in_the_code_lists_the_same_agents_in_the_same_order():
    schema_roles = get_args(AgentName)
    assert tuple(AGENTS) == schema_roles == tuple(casefile.ORDER)
    assert set(DELIBERATOR_NAMES) == set(schema_roles)
    assert set(schema_roles) <= set(get_args(Requester))    # agents can ask specialists for evidence


def test_every_role_has_a_prompt_and_no_prompt_is_left_over_from_a_rename():
    prompts = {p.stem for p in PROMPTS.glob("*.md")} - {"shared_rules"}
    assert prompts == set(get_args(AgentName))


def test_the_gate_uses_the_role_constant_not_a_string_literal():
    source = inspect.getsource(Facilitator._apply_cross_case_gate)
    assert "CROSS_CASE_ROLE" in source
    for role in (*get_args(AgentName), *OLD_NAMES):
        assert f'"{role}"' not in source and f"'{role}'" not in source, f"literal {role!r} in the gate"


@pytest.mark.parametrize("module", [facilitator_module, crosscase, rules, casefile])
def test_no_deliberation_code_still_names_a_role_that_was_renamed(module):
    source = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
    for old in OLD_NAMES:
        assert not re.search(rf"[\"']{old}[\"']", source), f"{module.__name__} still has the string {old!r}"


def test_a_gate_pointed_at_a_role_that_does_not_exist_is_caught_here_not_in_a_demo(monkeypatch):
    monkeypatch.setattr(crosscase, "CROSS_CASE_ROLE", "caseload")
    with pytest.raises(AssertionError):
        test_the_gate_names_a_role_that_is_on_the_real_roster()

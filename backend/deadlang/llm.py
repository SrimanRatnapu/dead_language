"""deadlang.llm — see docs/plans for ownership and contract."""


class BudgetExceeded(Exception):
    """Raised by the wrapper when a global or per-case token cap is hit (contract: plan 01 §4.5).

    Person C's placeholder so deliberation code can import it. Person B: replace this file with the
    real wrapper (call_json, call_vision_json, usage_snapshot); keep this class name.
    """

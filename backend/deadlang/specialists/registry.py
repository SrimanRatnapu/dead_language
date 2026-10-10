"""Build every specialist (contract: plan 01 §4.2). A class that is not written yet is skipped with a warning,
so local mode keeps working while the other specialists are still being built."""
from __future__ import annotations

import importlib
import logging
from typing import Any

from deadlang.specialists.base import Specialist

log = logging.getLogger("deadlang.registry")

SPECIALIST_CLASSES: list[tuple[str, str]] = [
    ("deadlang.specialists.price", "PriceChecker"),
    ("deadlang.specialists.network", "SellerInventory"),
    ("deadlang.specialists.network", "LinkedSellers"),
    ("deadlang.specialists.legal", "LegalTable"),
    ("deadlang.specialists.material", "ThoroughExaminer"),
    ("deadlang.specialists.material", "QuickExaminer"),
    ("deadlang.specialists.language", "Translator"),
]


def build_specialists(market: Any) -> list[Specialist]:
    built: list[Specialist] = []
    for module, cls_name in SPECIALIST_CLASSES:
        try:
            cls = getattr(importlib.import_module(module), cls_name)
        except (ImportError, AttributeError):
            log.warning("specialist %s.%s is not available yet; skipping", module, cls_name)
            continue
        built.append(cls(market))
    return built

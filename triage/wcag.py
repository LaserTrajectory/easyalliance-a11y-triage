"""WCAG 2.2 taxonomy loaded from data/wcag22.json (built by scripts/build_wcag.py)."""

import json
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "wcag22.json"


@cache
def taxonomy() -> dict:
    return json.loads(DATA.read_text())


def guidelines() -> list[dict]:
    return [g for p in taxonomy()["principles"] for g in p["guidelines"]]


def guideline(num: str) -> dict:
    return next(g for g in guidelines() if g["num"] == num)


def criterion(num: str) -> dict:
    return next(sc for g in guidelines() for sc in g["criteria"] if sc["num"] == num)


def guideline_of(sc_num: str) -> str:
    """'1.4.3' -> '1.4'."""
    return sc_num.rsplit(".", 1)[0]


def all_criteria() -> list[str]:
    return [sc["num"] for g in guidelines() for sc in g["criteria"]]

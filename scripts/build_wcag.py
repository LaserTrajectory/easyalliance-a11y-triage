"""Build data/wcag22.json from the W3C's official WCAG 2.2 JSON.

Keeps principles -> guidelines -> success criteria, drops 4.1.1 Parsing
(obsolete in WCAG 2.2), and keeps each criterion's one-sentence normative
text so it can be used directly as a Choice option description.

    python scripts/build_wcag.py
"""

import json
import re
import urllib.request
from pathlib import Path

SOURCE = "https://www.w3.org/WAI/WCAG22/wcag.json"
OUT = Path(__file__).resolve().parent.parent / "data" / "wcag22.json"
OBSOLETE = {"4.1.1"}


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    with urllib.request.urlopen(SOURCE) as resp:
        raw = json.load(resp)

    principles = []
    for p in raw["principles"]:
        guidelines = []
        for g in p["guidelines"]:
            criteria = [
                {
                    "num": sc["num"],
                    "handle": sc["handle"],
                    "level": sc.get("level", ""),
                    "text": clean(sc["title"]),
                }
                for sc in g["successcriteria"]
                if sc["num"] not in OBSOLETE
            ]
            guidelines.append(
                {"num": g["num"], "handle": g["handle"], "text": clean(g["title"]), "criteria": criteria}
            )
        principles.append({"num": p["num"], "handle": p["handle"], "guidelines": guidelines})

    n_g = sum(len(p["guidelines"]) for p in principles)
    n_sc = sum(len(g["criteria"]) for p in principles for g in p["guidelines"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"version": "2.2", "source": SOURCE, "principles": principles}, indent=2))
    print(f"Wrote {OUT.name}: {len(principles)} principles, {n_g} guidelines, {n_sc} success criteria")


if __name__ == "__main__":
    main()

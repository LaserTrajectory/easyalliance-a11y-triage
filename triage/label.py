"""Terminal labeling tool for data/issues_raw.jsonl -> data/labels.csv.

    python -m triage.label --labeler aniruddh          # label unlabeled issues
    python -m triage.label --export-review 30          # sample for expert spot-check

Each label: is it an a11y bug, which WCAG 2.2 success criterion (e.g. 1.4.3),
severity 0-2, and whether it has reproduction detail. Saved after every issue,
so you can stop any time with Ctrl-C or 'q'.
"""

import argparse
import csv
import json
import random
import textwrap
from pathlib import Path

from triage import questions, wcag

DATA = Path(__file__).resolve().parent.parent / "data"
FIELDS = ["id", "is_a11y_bug", "criterion", "severity", "has_repro", "labeler", "notes"]


def load_issues(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_labels(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open() as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def append_label(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def ask(prompt: str, valid) -> str:
    while True:
        v = input(prompt).strip()
        if v == "q":
            raise KeyboardInterrupt
        if valid(v):
            return v
        print("    ? try again (q to quit)")


def show(issue: dict, full: bool = False) -> None:
    body = issue["body"] if full else issue["body"][:1500]
    print("\n" + "=" * 78)
    print(f"{issue['id']}   {issue['url']}")
    print(f"TITLE: {issue['title']}\n")
    print(textwrap.indent(body, "  "))
    if not full and len(issue["body"]) > 1500:
        print("  … (type 'm' at the first prompt to see the rest)")


def label_loop(issues_path: Path, labels_path: Path, labeler: str) -> None:
    done = load_labels(labels_path)
    todo = [i for i in load_issues(issues_path) if i["id"] not in done]
    print(f"{len(done)} labeled, {len(todo)} to go. Criteria list: data/wcag22.json")
    valid_sc = set(wcag.all_criteria())
    for issue in todo:
        show(issue)
        a = ask("\n  a11y bug? [y/n, s=skip, m=more]: ", lambda v: v in {"y", "n", "s", "m"})
        if a == "m":
            show(issue, full=True)
            a = ask("  a11y bug? [y/n, s=skip]: ", lambda v: v in {"y", "n", "s"})
        if a == "s":
            continue
        row = {"id": issue["id"], "is_a11y_bug": int(a == "y"), "labeler": labeler,
               "criterion": "", "severity": "", "has_repro": ""}
        if a == "y":
            sc = ask("  WCAG criterion (e.g. 1.4.3, ?=unsure): ", lambda v: v in valid_sc or v == "?")
            if sc != "?":
                print(f"    -> {sc} {wcag.criterion(sc)['handle']}")
            row["criterion"] = "" if sc == "?" else sc
            for i, lvl in enumerate(questions.SEVERITY_LEVELS):
                print(f"    {i} {lvl}")
            row["severity"] = ask("  severity [0/1/2]: ", lambda v: v in {"0", "1", "2"})
        row["has_repro"] = int(ask("  enough detail to reproduce? [y/n]: ", lambda v: v in {"y", "n"}) == "y")
        row["notes"] = input("  notes (optional): ").strip()
        append_label(labels_path, row)


def export_review(issues_path: Path, labels_path: Path, n: int, seed: int = 0) -> None:
    issues = {i["id"]: i for i in load_issues(issues_path)}
    labels = list(load_labels(labels_path).values())
    sample = random.Random(seed).sample(labels, min(n, len(labels)))
    out = DATA / "expert_review.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "url", "title", "our_is_a11y", "our_criterion", "our_severity",
                    "expert_agrees (y/n)", "expert_criterion", "expert_severity", "expert_notes"])
        for row in sample:
            i = issues[row["id"]]
            w.writerow([row["id"], i["url"], i["title"], row["is_a11y_bug"], row["criterion"], row["severity"]])
    print(f"Wrote {len(sample)} rows to {out} for expert spot-check")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issues", type=Path, default=DATA / "issues_raw.jsonl")
    ap.add_argument("--labels", type=Path, default=DATA / "labels.csv")
    ap.add_argument("--labeler", default="me")
    ap.add_argument("--export-review", type=int, metavar="N")
    args = ap.parse_args()
    if args.export_review:
        export_review(args.issues, args.labels, args.export_review)
        return
    try:
        label_loop(args.issues, args.labels, args.labeler)
    except (KeyboardInterrupt, EOFError):
        print("\nSaved. Run again to continue.")


if __name__ == "__main__":
    main()

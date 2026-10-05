"""Collect real accessibility bug reports from public GitHub issues.

Uses the GitHub CLI (`gh`, must be logged in). Searches issues carrying an
accessibility label for assistive-tech / WCAG keywords, filters out
non-reports (empty bodies, release checklists, bot output), dedupes, and
writes data/issues_raw.jsonl for labeling.

    python scripts/collect_issues.py                  # default queries, ~400 candidates
    python scripts/collect_issues.py --per-query 50 --repo mui/material-ui
"""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "issues_raw.jsonl"

LABELS = ["accessibility", "a11y"]
KEYWORDS = [
    "screen reader", "VoiceOver", "NVDA", "JAWS", "TalkBack", "keyboard",
    "focus", "contrast", "alt text", "aria-label", "caption", "zoom", "WCAG",
]
# A report must mention at least one of these to count as an a11y bug candidate.
SIGNAL = re.compile(
    r"screen ?reader|voiceover|nvda|jaws|talkback|keyboard|focus|contrast|alt[ -]text|aria|"
    r"caption|zoom|wcag|accessib|a11y|tab order|announce",
    re.I,
)
BOT = re.compile(r"\[bot\]|dependabot|renovate", re.I)
# Reports that already cite a criterion ("WCAG 2.5.3: Label in Name") would leak the answer.
SC_REF = re.compile(r"\b[1-4]\.\d{1,2}\.\d{1,2}\b|success criteri", re.I)
# Agent-written audit tickets aren't the human tester reports we want to triage.
AI_TITLE = re.compile(r"^\s*[\[(](claude|codex|copilot|ai|gpt)[\])]", re.I)
MIN_BODY, MAX_BODY = 120, 4000
PER_REPO = 6  # keep the dataset from being dominated by one project


def search(query: str, label: str, limit: int, repo: str | None) -> list[dict]:
    # comments:>=1 favors issues a human actually engaged with over drive-by agent tickets.
    cmd = [
        "gh", "search", "issues", query, "comments:>=1", "--label", label, "--limit", str(limit),
        "--json", "title,body,url,repository,labels,number,state,createdAt,author",
    ]
    if repo:
        cmd += ["--repo", repo]
    for attempt in range(3):
        time.sleep(2.5)  # GitHub search allows ~30 requests/minute
        out = subprocess.run(cmd, capture_output=True, text=True)
        if "rate limit" not in out.stderr:
            break
        print("  rate limited; waiting 60s")
        time.sleep(60)
    if out.returncode != 0:
        print(f"  ! gh failed for {query!r}/{label}: {out.stderr.strip()[:200]}")
        return []
    return json.loads(out.stdout or "[]")


def keep(issue: dict) -> bool:
    body = issue.get("body") or ""
    if len(body) < MIN_BODY or BOT.search((issue.get("author") or {}).get("login", "")):
        return False
    if body.count("- [ ]") > 8:  # release/tracking checklists, not bug reports
        return False
    if SC_REF.search(issue["title"] + " " + body) or AI_TITLE.search(issue["title"]):
        return False
    return bool(SIGNAL.search(issue["title"] + " " + body))


def tidy(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # issue-template comments
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", text)  # images can't be sent to Jev yet
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_BODY]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=20)
    ap.add_argument("--repo", help="restrict to one repo, e.g. owner/name")
    args = ap.parse_args()

    seen: dict[str, dict] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            row = json.loads(line)
            seen[row["url"]] = row

    before = len(seen)
    per_repo: dict[str, int] = {}
    for row in seen.values():
        per_repo[row["repo"]] = per_repo.get(row["repo"], 0) + 1
    for label in LABELS:
        for kw in KEYWORDS:
            for issue in search(kw, label, args.per_query, args.repo):
                repo = issue["repository"]["nameWithOwner"]
                if issue["url"] in seen or per_repo.get(repo, 0) >= PER_REPO or not keep(issue):
                    continue
                per_repo[repo] = per_repo.get(repo, 0) + 1
                seen[issue["url"]] = {
                    "id": f"{repo}#{issue['number']}",
                    "url": issue["url"],
                    "repo": repo,
                    "title": issue["title"],
                    "body": tidy(issue["body"]),
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "state": issue["state"],
                    "created_at": issue["createdAt"],
                }
        print(f"label:{label} done, {len(seen)} candidates so far")

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w") as f:
        for row in seen.values():
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(seen)} issues ({len(seen) - before} new) to {OUT.name}")


if __name__ == "__main__":
    main()

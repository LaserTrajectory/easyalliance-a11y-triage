"""Collect GitHub accessibility issues whose author cited a WCAG criterion, as labeled data.

collect_issues.py drops reports that cite a criterion because the answer leaks.
Here they are the point: the cited criterion becomes the label, and every
citation is redacted from the title and body before any model sees them.

Only issues created before --before (default 2023-01-01) are used. Since 2024,
AI agents file large numbers of WCAG-citing tickets, and a criterion an LLM
picked is not ground truth.

Writes data/issues_cited.jsonl and data/labels_cited.csv (same formats as
issues_raw.jsonl / labels.csv). Only the criterion is labeled; severity and
has_repro are left blank, and every row is an a11y bug by construction.

    python scripts/collect_cited.py
    python -m triage.run_eval --backend jev --issues data/issues_cited.jsonl --labels data/labels_cited.csv --run jev_cited
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from collect_issues import AI_TITLE, BOT, MIN_BODY, tidy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from triage import wcag  # noqa: E402
from triage.label import FIELDS  # noqa: E402

OUT_ISSUES = ROOT / "data" / "issues_cited.jsonl"
OUT_LABELS = ROOT / "data" / "labels_cited.csv"
OUT_LABELS_CLEAN = ROOT / "data" / "labels_cited_clean.csv"

CRITERIA = {sc["num"]: sc for g in wcag.guidelines() for sc in g["criteria"]}
REMOVED = {"4.1.1"}  # Parsing: dropped in WCAG 2.2, so it can't be a label

GENERIC_QUERIES = [
    ('"success criterion"', "accessibility"),
    ('"success criterion"', "a11y"),
    ('"success criterion"', "508"),
    ('"Trusted Tester"', None),
    ('"fails WCAG"', None),
]
# One query per criterion keeps 1.4.3 and 4.1.2 from crowding out everything else.
PER_CRITERION_QUERY = 'WCAG "{num}"'

SC_NUM = r"(?<![\d.])[1-4]\.\d{1,2}\.\d{1,2}(?![.]?\d)"
# A number only counts as a citation near words like these (otherwise "version 2.1.1" would).
CONTEXT = re.compile(r"wcag|\bsc\b|success criteri|criteri|guideline|checkpoint|508|trusted tester|level\s*a", re.I)
# A trailing "s" is optional: reports write "Info and Relationship" too.
HANDLES = "|".join(re.escape(h.removesuffix("s")) + ("s?" if h.endswith("s") else "")
                   for h in sorted((sc["handle"] for sc in CRITERIA.values()), key=len, reverse=True))
# "WCAG 2.1 AA Success Criterion 1.4.3 Contrast (Minimum) (Level AA)" -> one redaction, whatever parts are present.
# The criterion's name may also come first: "Name, Role, Value 4.1.2".
CITATION = re.compile(
    rf"(?:\b(?:{HANDLES})\s*[-–—:,]?\s*\(?)?"
    r"(?:\bWCAG\s*(?:2(?:\.[0-2])?)?\s*(?-i:(?:Level\s*)?A{1,3})?\s*[-–—:,]?\s*)?"
    r"(?:\b(?:Success\s+Criteri(?:on|a)|SC|Criteri(?:on|a)|Guideline)\s*[:#]?\s*)?"
    + SC_NUM
    + rf"(?:\s*[-–—:,]?\s*\(?(?:{HANDLES})\)?)?"
    r"(?:[\s,]*\(?(?-i:(?:Level\s*)?A{1,3})\)?(?!\w))?",
    re.I,
)
TECHNIQUE = re.compile(r"\b((?:technique|failure)s?\s*[:#]?\s*)(?:ARIA|SCR|SVR|PDF|SM|SL|FLASH|[FGHCT])\d{1,3}\b", re.I)
# W3C pages, and any link whose path names WCAG or a criterion (webaim.org/standards/wcag/checklist#sc2.4.4).
WCAG_LINK = re.compile(
    r"https?://\S*(?:w3\.org/(?:WAI|TR)|wcag|understanding|#sc)\S*"
    r"|\S*w3\.org/(?:WAI|TR)/[^\s\])]*",  # also scheme-less, e.g. as markdown link text
    re.I,
)
SECTION_508 = re.compile(r"\b1194\.\d+(?:\s*\([a-z0-9]+\))*", re.I)
AI_BODY = re.compile(r"generated with \[?claude|claude code|co-authored-by: claude|copilot|chatgpt", re.I)
# Spec and checker repos cite criteria to discuss rules, not to report a barrier in a product.
TOOL_REPO = re.compile(
    r"^(w3c|act-rules|dequelabs|IBMa|veraPDF|jsx-eslint|WCAG-Audit-Discussions|DISIC|BIK-BITV)/"
    r"|accessibility-insights|a11ychecker|WebAccessibilityToolbar|lint",
    re.I,
)
# Pasted checker output ("Ensures every HTML document has a lang attribute") nearly names the criterion.
AUTOMATED = re.compile(r"accessibility insights|\baxe\b|\bEnsures (?:every|the|that|all|elements|images|ARIA)", re.I)
EN_WORDS = set("the and is to of a in it this that for on with not be are as can when there".split())
OTHER_WORDS = set("de la el los las que und der die das ist nicht het een van och att ja og ikke er på ei le les des et est pas il con una por para".split())


def english(text: str) -> bool:
    words = re.findall(r"[a-zåäöøæéèü']+", text.lower())
    return sum(w in EN_WORDS for w in words) > sum(w in OTHER_WORDS for w in words)
MERGE = re.compile(r"\[…\](?:\s*(?:,|;|/|&|and|or)?\s*\[…\])+")


def cited(text: str) -> set[str]:
    """Criterion numbers the text cites, counting a number only when citation context is near it."""
    found = set()
    for m in re.finditer(SC_NUM, text):
        num = m.group()
        before = text[max(0, m.start() - 60) : m.start()]
        after = text[m.end() : m.end() + 60].lstrip(" -–—:,(").lower()
        handle = CRITERIA[num]["handle"].lower() if num in CRITERIA else None
        named = handle and (after.startswith(handle) or before.rstrip(" -–—:,(").lower().endswith(handle))
        if CONTEXT.search(before) or named or (found and re.search(SC_NUM, before)):
            found.add(num)
    return found


def redact(text: str) -> str:
    text = WCAG_LINK.sub("[link]", text)
    text = TECHNIQUE.sub(r"\1[…]", text)
    text = SECTION_508.sub("[…]", text)
    text = CITATION.sub("[…]", text)
    text = re.sub(SC_NUM, "[…]", text)  # anything the citation pattern missed
    return MERGE.sub("[…]", text)


def search(query: str, label: str | None, limit: int, before: str) -> list[dict]:
    cmd = [
        "gh", "search", "issues", query, "--created", f"<{before}", "--limit", str(limit),
        "--json", "title,body,url,repository,labels,number,state,createdAt,author",
    ]
    if label:
        cmd += ["--label", label]
    for _ in range(3):
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


def candidate(issue: dict) -> tuple[str, str] | None:
    """(criterion, citation snippet) if the issue cites exactly one usable criterion, else None."""
    title, body = issue["title"], issue.get("body") or ""
    if BOT.search((issue.get("author") or {}).get("login", "")) or AI_TITLE.search(title) or AI_BODY.search(body):
        return None
    if body.count("- [ ]") > 8:  # audit checklists, not single findings
        return None
    if TOOL_REPO.search(issue["repository"]["nameWithOwner"]) or not english(title + " " + body):
        return None
    nums = cited(title + "\n" + body)
    if len(nums) != 1 or nums & REMOVED or not nums <= CRITERIA.keys():
        return None
    num = nums.pop()
    text = title + " " + body
    i = text.find(num)
    return num, " ".join(text[max(0, i - 40) : i + 60].split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="2023-01-01", help="only issues created before this date")
    ap.add_argument("--per-query", type=int, default=100)
    ap.add_argument("--per-repo", type=int, default=8, help="keep one audit repo from dominating")
    ap.add_argument("--per-criterion", type=int, default=25, help="keep 1.4.3 / 4.1.2 from dominating")
    args = ap.parse_args()

    issues: dict[str, dict] = {}
    labels: dict[str, dict] = {}
    if OUT_ISSUES.exists() and OUT_LABELS.exists():
        issues = {r["id"]: r for r in map(json.loads, OUT_ISSUES.read_text().splitlines())}
        with OUT_LABELS.open() as f:
            labels = {r["id"]: r for r in csv.DictReader(f)}
    per_repo: dict[str, int] = {}
    per_sc: dict[str, int] = {}
    for iid, row in issues.items():
        per_repo[row["repo"]] = per_repo.get(row["repo"], 0) + 1
        per_sc[labels[iid]["criterion"]] = per_sc.get(labels[iid]["criterion"], 0) + 1
    before = len(issues)

    queries = GENERIC_QUERIES + [(PER_CRITERION_QUERY.format(num=n), None) for n in CRITERIA]
    for qi, (query, label) in enumerate(queries, 1):
        for issue in search(query, label, args.per_query, args.before):
            repo = issue["repository"]["nameWithOwner"]
            iid = f"{repo}#{issue['number']}"
            if iid in issues or per_repo.get(repo, 0) >= args.per_repo:
                continue
            hit = candidate(issue)
            if not hit or per_sc.get(hit[0], 0) >= args.per_criterion:
                continue
            title, body = redact(issue["title"]), tidy(redact(issue.get("body") or ""))
            if len(body) < MIN_BODY:  # too thin once the citation is gone
                continue
            num, snippet = hit
            per_repo[repo] = per_repo.get(repo, 0) + 1
            per_sc[num] = per_sc.get(num, 0) + 1
            issues[iid] = {
                "id": iid,
                "url": issue["url"],
                "repo": repo,
                "title": title,
                "body": body,
                "labels": [l["name"] for l in issue.get("labels", [])],
                "state": issue["state"],
                "created_at": issue["createdAt"],
                # The criterion's name still appearing (e.g. "status messages") is a hint worth slicing on.
                "handle_in_text": CRITERIA[num]["handle"].lower() in (title + " " + body).lower(),
                "automated": bool(AUTOMATED.search(title + " " + body)),
            }
            labels[iid] = {"id": iid, "is_a11y_bug": 1, "criterion": num, "severity": "", "has_repro": "",
                           "labeler": "cited", "notes": f"cited: {snippet}"}
        if qi % 10 == 0 or qi == len(queries):
            print(f"  {qi}/{len(queries)} queries, {len(issues)} issues")

    OUT_ISSUES.write_text("".join(json.dumps(r) + "\n" for r in issues.values()))
    # The clean file drops the easier rows; `triage.report --labels` scores only ids in the file it is given.
    clean = [l for iid, l in labels.items() if not issues[iid]["handle_in_text"] and not issues[iid]["automated"]]
    for path, rows in ((OUT_LABELS, labels.values()), (OUT_LABELS_CLEAN, clean)):
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {len(issues)} issues ({len(issues) - before} new) across {len(per_sc)} criteria; {len(clean)} clean")
    print("Most common: " + ", ".join(f"{k} ({v})" for k, v in sorted(per_sc.items(), key=lambda kv: -kv[1])[:8]))


if __name__ == "__main__":
    main()

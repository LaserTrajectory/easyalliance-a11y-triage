# Accessibility triage eval (Jev vs. LLM)

A prototype for Easy Alliance Project 1 (the accessibility-testing marketplace):
take a free-text accessibility bug report and decide

- is it a real accessibility barrier?
- which WCAG 2.2 success criterion does it fail?
- how severe is it, and does it have enough detail to reproduce?
- can it be auto-triaged, or should an expert look at it?

The model only answers narrow typed questions (Choice / Score / Noul). Plain
code in `triage/pipeline.py` combines the answers and makes the routing
decision. The harness measures whether the model's confidence can be trusted
enough to route on.

## Setup

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in only the keys you have
.venv/bin/python -m triage.check_keys          # which keys are set (free)
.venv/bin/python -m triage.check_keys --live   # confirm Jev accepts your key (one call, < $0.0001)
```

`.env` is loaded automatically; a key already set in your shell takes precedence.
Key values are never printed.

## Workflow

| Step | Command | Cost |
|---|---|---|
| Build WCAG 2.2 list from W3C | `python scripts/build_wcag.py` | free |
| Collect GitHub a11y issues | `python scripts/collect_issues.py` | free |
| Label issues | `python -m triage.label --labeler yourname` | free, your time |
| Or: collect issues pre-labeled by a cited criterion | `python scripts/collect_cited.py` | free |
| Jev on the cited set, tuning half | `python -m triage.run_eval --backend jev --issues data/issues_cited.jsonl --labels data/labels_cited.csv --split dev --run <name>` | ~$0.03 for 271 issues |
| Then once, the held-out half | same with `--split test`, then `python -m triage.report results/<name>.jsonl --labels data/labels_cited.csv --split test` | ~$0.03 for 255 issues |
| Expert spot-check sample | `python -m triage.label --export-review 30` | expert's time |
| Check API keys | `python -m triage.check_keys --live` | < $0.0001 |
| Offline plumbing run | `python -m triage.run_eval --backend mock` | free |
| LLM baseline | `python -m triage.run_eval --backend adapter --provider anthropic --model claude-haiku-4-5-20251001` | LLM tokens |
| Jev run | `python -m triage.run_eval --backend jev --max-usd 1` | ~$0.06 for all 561 issues |
| Compare runs | `python -m triage.report` | free |
| Live demo, one report | `python -m triage.demo "VoiceOver reads the close button as just 'button'"` | free with mock |

Run commands from this folder with `.venv/bin/python` (or activate the venv).

Try everything right now without keys or labels using the synthetic demo set:

```bash
.venv/bin/python -m triage.run_eval --backend mock --issues data/demo/issues.jsonl --labels data/demo/labels.csv --run demo_mock
```

`data/demo/` is 12 synthetic reports written for plumbing tests. Never report numbers from it.

## Labeling guide

- **a11y bug = yes** if the report names a specific barrier that exists in the product now,
  even when phrased as a fix ("the search icon has no alt text").
  **No** for feature requests, questions, CI/tooling, docs-only work, and goal checklists or
  audit plans ("make the whole app keyboard accessible") that name no barrier anyone has hit.
- **Criterion**: the single best WCAG 2.2 success criterion (`data/wcag22.json`).
  At the prompt, type a word (`focus`) or a guideline (`2.4`) to list candidates.
  Use `?` if you genuinely can't decide; those are excluded from criterion metrics.
- **Severity**: 0 minor, 1 a workaround exists, 2 blocks some disabled users entirely.
- **Has repro**: could a tester reproduce it from the report alone?
- Skip (`s`) non-English or unreadable issues rather than guessing.

## Layout

```
scripts/build_wcag.py      W3C WCAG 2.2 JSON -> data/wcag22.json (86 criteria, 4.1.1 dropped)
scripts/collect_issues.py  gh search -> data/issues_raw.jsonl (filters leaks, bots, agent tickets)
scripts/collect_cited.py   gh search -> data/issues_cited.jsonl + labels_cited.csv (cited criterion = label, redacted)
triage/questions.py        the Choice/Score/Noul questions, two-stage WCAG mapping
triage/backends.py         mock | jev | adapter, all returning one normalized Reply
triage/pipeline.py         two calls + deterministic routing policy
triage/metrics.py          accuracy, ECE, Brier, coverage-vs-accuracy
triage/run_eval.py         cached, budget-capped eval runs -> results/
triage/report.py           per-run report and side-by-side comparison
triage/label.py            terminal labeling tool + expert review export
```

## Design notes

- **Two-stage WCAG mapping.** Guideline (13 options + "none"), then criterion within it
  (at most 13). Fits OpenJev's 52-option cap as well as Jev's 255, and follows TypeSafe's
  advice to decompose questions. Criterion confidence is the joint probability across both stages.
  Each guideline option lists its criteria's names: with only the guideline's one-line text, Jev
  almost never put reflow or hover content under 1.4 (Reflow was 0 of 22 right).
- **Dev/test split.** `--split dev|test` (run_eval and report) keeps one half of any label file,
  fixed by a hash of the issue id. Change wording or thresholds looking only at dev; run test once
  at the end and report that number.
- **Leakage filter.** Issues that already cite a criterion number are dropped at collection,
  or the test would be trivial.
- **Cited set.** `collect_cited.py` keeps exactly those issues instead: the criterion the author cited
  becomes the label, and citations, criterion names next to them, technique codes and WCAG links are
  redacted. Only issues created before 2023 (since 2024 most WCAG-citing tickets are agent-written),
  in English, citing exactly one criterion, outside spec and checker repos. Only the criterion is
  labeled. Rows flagged `handle_in_text` (the criterion's name still appears in the report) or
  `automated` (pasted checker output) are easier; `labels_cited_clean.csv` leaves them out, so
  `python -m triage.report results/jev_cited.jsonl --labels data/labels_cited_clean.csv` scores the harder subset.
- **Spend safety.** Jev runs show a conservative pre-flight estimate (fit to real usage; runs
  have cost about 20% less), ask for confirmation, stop at `--max-usd`, and cache every result
  so nothing is paid for twice.
- **Routing.** Reports re-apply the policy in `pipeline.py` to cached results, so changing it
  costs no model calls. The thresholds are placeholders: set them from the coverage/accuracy
  table in the Jev report, not by guessing. A report that may lack reproduction detail doesn't
  go to an expert for that; it's flagged `ask_tester` so the tester is asked for more.
- **Only title and body are sent** to any model. No URLs, usernames or repo metadata.

See `OPEN_ISSUES.md` for what's deliberately not done yet.

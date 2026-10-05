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
```

## Workflow

| Step | Command | Cost |
|---|---|---|
| Build WCAG 2.2 list from W3C | `python scripts/build_wcag.py` | free |
| Collect GitHub a11y issues | `python scripts/collect_issues.py` | free |
| Label issues | `python -m triage.label --labeler yourname` | free, your time |
| Expert spot-check sample | `python -m triage.label --export-review 30` | expert's time |
| Offline plumbing run | `python -m triage.run_eval --backend mock` | free |
| LLM baseline | `python -m triage.run_eval --backend adapter --provider anthropic --model claude-haiku-4-5-20251001` | LLM tokens |
| Jev run | `python -m triage.run_eval --backend jev --max-usd 1` | ~$0.05 for all 561 issues |
| Compare runs | `python -m triage.report` | free |
| Live demo, one report | `python -m triage.demo "VoiceOver reads the close button as just 'button'"` | free with mock |

Run commands from this folder with `.venv/bin/python` (or activate the venv).
Load keys first with `set -a; source .env; set +a`.

Try everything right now without keys or labels using the synthetic demo set:

```bash
.venv/bin/python -m triage.run_eval --backend mock --issues data/demo/issues.jsonl --labels data/demo/labels.csv --run demo_mock
```

`data/demo/` is 12 synthetic reports written for plumbing tests. Never report numbers from it.

## Labeling guide

- **a11y bug = yes** if the report describes a barrier disabled users hit in the product,
  including "make X keyboard accessible" tasks that imply a current barrier.
  **No** for feature requests, questions, CI/tooling, docs-only work.
- **Criterion**: the single best WCAG 2.2 success criterion (`data/wcag22.json`).
  Use `?` if you genuinely can't decide; those are excluded from criterion metrics.
- **Severity**: 0 minor, 1 a workaround exists, 2 blocks some disabled users entirely.
- **Has repro**: could a tester reproduce it from the report alone?
- Skip (`s`) non-English or unreadable issues rather than guessing.

## Layout

```
scripts/build_wcag.py      W3C WCAG 2.2 JSON -> data/wcag22.json (86 criteria, 4.1.1 dropped)
scripts/collect_issues.py  gh search -> data/issues_raw.jsonl (filters leaks, bots, agent tickets)
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
- **Leakage filter.** Issues that already cite a criterion number are dropped at collection,
  or the test would be trivial.
- **Spend safety.** Jev runs show a pre-flight estimate, ask for confirmation, stop at
  `--max-usd`, and cache every result so nothing is paid for twice.
- **Routing thresholds** in `pipeline.py` are placeholders. Set them from the
  coverage/accuracy table in the Jev report, not by guessing.
- **Only title and body are sent** to any model. No URLs, usernames or repo metadata.

See `OPEN_ISSUES.md` for what's deliberately not done yet.

"""Run the triage pipeline over labeled issues and write a report.

    python -m triage.run_eval --backend mock
    python -m triage.run_eval --backend adapter --provider anthropic --model claude-haiku-4-5-20251001
    python -m triage.run_eval --backend jev --max-usd 1.00

Results are cached per run in results/<run>.jsonl, so an interrupted or
re-run job never pays twice for the same issue. For paid backends a
pre-flight estimate is shown and the run stops once --max-usd is spent.
"""

import argparse
import json
import re
from pathlib import Path

from triage import backends, questions, report, wcag
from triage.label import load_issues, load_labels
from triage.pipeline import triage

ROOT = Path(__file__).resolve().parent.parent


def preflight_usd(issues: list[dict]) -> float:
    widest = max(wcag.guidelines(), key=lambda g: len(g["criteria"]))["num"]
    tokens = sum(
        backends.estimate_tokens(questions.state(i), questions.stage1())
        + backends.estimate_tokens(questions.state(i), questions.stage2(widest))
        for i in issues
    )
    return tokens * backends.JEV_USD_PER_MTOK / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["mock", "jev", "adapter"], default="mock")
    ap.add_argument("--provider", help="adapter only: openai | anthropic | gemini")
    ap.add_argument("--model", help="jev model alias or adapter model id")
    ap.add_argument("--usd-per-mtok", type=float, default=0.0, help="adapter only: blended price for cost tracking")
    ap.add_argument("--issues", type=Path, default=ROOT / "data" / "issues_raw.jsonl")
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "labels.csv")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-usd", type=float, default=1.00, help="hard stop on spend for this run")
    ap.add_argument("--run", help="run name (default: derived from backend)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt for paid backends")
    args = ap.parse_args()

    labels = load_labels(args.labels)
    issues = [i for i in load_issues(args.issues) if i["id"] in labels][: args.limit]
    if not issues:
        raise SystemExit(f"No labeled issues: label some first (python -m triage.label) or check {args.labels}")

    backend = backends.make(args.backend, args.provider, args.model, args.usd_per_mtok)
    run = args.run or re.sub(r"[^\w.-]+", "_", backend.name)
    out = ROOT / "results" / f"{run}.jsonl"
    out.parent.mkdir(exist_ok=True)

    done = {}
    if out.exists():
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done[row["id"]] = row["result"]
    todo = [i for i in issues if i["id"] not in done]

    print(f"{backend.name}: {len(issues)} labeled issues, {len(done)} cached, {len(todo)} to run")
    if args.backend == "jev" and todo:
        est = preflight_usd(todo)
        print(f"Estimated Jev cost: ${est:.4f} (upper bound, 2 calls/issue). Hard stop at ${args.max_usd:.2f}.")
        if est > args.max_usd:
            raise SystemExit("Estimate exceeds --max-usd; lower --limit or raise --max-usd.")
        if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
            raise SystemExit("Aborted.")

    spent = 0.0
    with out.open("a") as f:
        for n, issue in enumerate(todo, 1):
            if spent >= args.max_usd:
                print(f"Reached --max-usd ${args.max_usd:.2f}; stopping. Re-run to continue.")
                break
            try:
                t = triage(issue, backend)
            except Exception as e:  # keep going; one bad issue shouldn't kill a paid run
                print(f"  ! {issue['id']}: {type(e).__name__}: {e}")
                continue
            spent += t.cost_usd
            done[issue["id"]] = t.to_dict()
            f.write(json.dumps({"id": issue["id"], "backend": backend.name, "result": t.to_dict()}) + "\n")
            f.flush()
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  spent ${spent:.4f}")

    path = report.write(run, backend.name, [(labels[i], done[i]) for i in done if i in labels])
    print(f"Report: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""Markdown reports: one per run, plus a side-by-side comparison.

    python -m triage.report                      # compare every run in results/
    python -m triage.report results/mock.jsonl results/jev_jev-latest.jsonl
    python -m triage.report --labels data/demo/labels.csv results/demo_mock.jsonl
"""

import argparse
import json
from pathlib import Path

from triage.label import load_labels
from triage.metrics import evaluate

ROOT = Path(__file__).resolve().parent.parent


def _pct(x):
    return "n/a" if x != x else f"{100 * x:.1f}%"


def _f(x, d=3):
    return "n/a" if x != x else f"{x:.{d}f}"


def render(backend: str, m: dict) -> str:
    c, r, u = m["criterion"], m["routing"], m["usage"]
    lines = [
        f"# Triage eval: `{backend}`",
        "",
        f"{m['n']} labeled issues. Mock results are keyword heuristics, not a model."
        if backend == "mock" else f"{m['n']} labeled issues.",
        "",
        "## Accuracy and calibration",
        "",
        "| Question | n | Accuracy | ECE (lower is better) | Brier |",
        "|---|---|---|---|---|",
        f"| Is an a11y bug | {m['is_a11y_bug']['n']} | {_pct(m['is_a11y_bug']['accuracy'])} | {_f(m['is_a11y_bug']['ece'])} | {_f(m['is_a11y_bug']['brier'])} |",
        f"| WCAG guideline | {m['guideline']['n']} | {_pct(m['guideline']['accuracy'])} | {_f(m['guideline']['ece'])} | |",
        f"| WCAG success criterion | {c['n']} | {_pct(c['accuracy'])} | {_f(c['ece'])} | |",
        f"| Has repro detail | {m['has_repro']['n']} | {_pct(m['has_repro']['accuracy'])} | {_f(m['has_repro']['ece'])} | {_f(m['has_repro']['brier'])} |",
        "",
        f"Severity: mean absolute error {_f(m['severity']['mae'], 2)} levels, exact match {_pct(m['severity']['exact'])} (n={m['severity']['n']}).",
        "",
        "## If we only auto-triage above a confidence threshold",
        "",
        "Coverage = share of issues handled without an expert. Accuracy = how often those were right.",
        "",
        "| Threshold | Coverage | Accuracy |",
        "|---|---|---|",
        *[f"| {s['threshold']:.2f} | {_pct(s['coverage'])} | {_pct(s['accuracy'])} |" for s in m["selective"]],
        "",
        "## Reliability (success criterion)",
        "",
        "Well calibrated means the two right-hand columns roughly match.",
        "",
        "| Confidence bin | n | Mean confidence | Actual accuracy |",
        "|---|---|---|---|",
        *[f"| {b['bin']} | {b['n']} | {_pct(b['confidence'])} | {_pct(b['accuracy'])} |" for b in c["reliability"]],
        "",
        "## Routing with current policy",
        "",
        f"auto: {r['counts']['auto']}, expert review: {r['counts']['expert_review']}, not a11y: {r['counts']['not_a11y']}",
        "",
        f"- Auto-routed with the wrong criterion: {len(r['auto_but_wrong_criterion'])} {r['auto_but_wrong_criterion'][:10]}",
        f"- Real bugs the model marked not-a11y: {len(r['real_bugs_marked_not_a11y'])} {r['real_bugs_marked_not_a11y'][:10]}",
        "",
        "## Usage",
        "",
        f"{u['input_tokens']:,} input tokens, ${u['cost_usd']:.4f} total, latency p50 {u['latency_p50_ms']:.0f} ms / p95 {u['latency_p95_ms']:.0f} ms per issue (2 calls).",
    ]
    return "\n".join(lines) + "\n"


def write(run: str, backend: str, rows: list[tuple[dict, dict]]) -> Path:
    path = ROOT / "results" / f"{run}_report.md"
    path.write_text(render(backend, evaluate(rows)))
    return path


def compare(paths: list[Path], labels_path: Path = ROOT / "data" / "labels.csv") -> str:
    labels = load_labels(labels_path)
    out = [
        "| Backend | n | Criterion acc | Criterion ECE | Coverage @0.8 | Acc @0.8 | a11y-bug acc | Cost | p50 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in paths:
        rows, backend = [], p.stem
        for line in p.read_text().splitlines():
            row = json.loads(line)
            backend = row["backend"]
            if row["id"] in labels:
                rows.append((labels[row["id"]], row["result"]))
        m = evaluate(rows)
        s8 = next(s for s in m["selective"] if s["threshold"] == 0.8)
        out.append(
            f"| {backend} | {m['n']} | {_pct(m['criterion']['accuracy'])} | {_f(m['criterion']['ece'])} | "
            f"{_pct(s8['coverage'])} | {_pct(s8['accuracy'])} | {_pct(m['is_a11y_bug']['accuracy'])} | "
            f"${m['usage']['cost_usd']:.4f} | {m['usage']['latency_p50_ms']:.0f} |"
        )
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*", type=Path)
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "labels.csv")
    args = ap.parse_args()
    print(compare(args.runs or sorted((ROOT / "results").glob("*.jsonl")), args.labels))

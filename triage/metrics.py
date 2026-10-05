"""Accuracy, calibration and selective-accuracy metrics over (label, result) pairs.

Calibration is the claim that matters for accessibility: if the model says 0.9
it should be right ~90% of the time, otherwise confidence-gated routing to a
human expert can't be trusted.
"""

import statistics

THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]


def ece(pairs: list[tuple[float, bool]], bins: int = 10) -> tuple[float, list[dict]]:
    """Expected calibration error over (confidence, correct) pairs, plus the bin table."""
    table, total, n = [], 0.0, len(pairs)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(c, ok) for c, ok in pairs if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if not inside:
            continue
        conf = statistics.mean(c for c, _ in inside)
        acc = statistics.mean(ok for _, ok in inside)
        total += len(inside) / n * abs(conf - acc)
        table.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(inside), "confidence": conf, "accuracy": acc})
    return (total if n else float("nan")), table


def brier(pairs: list[tuple[float, bool]]) -> float:
    return statistics.mean((p - y) ** 2 for p, y in pairs) if pairs else float("nan")


def _noul_pairs(rows, key):
    return [(r[key], bool(int(lab[key]))) for lab, r in rows if lab.get(key) not in ("", None)]


def _conf_correct(pairs):
    return [(max(p, 1 - p), (p >= 0.5) == y) for p, y in pairs]


def evaluate(rows: list[tuple[dict, dict]]) -> dict:
    """rows: (label row from labels.csv, Triage.to_dict()) pairs."""
    m: dict = {"n": len(rows)}

    for key in ("is_a11y_bug", "has_repro"):
        pairs = _noul_pairs(rows, key)
        cc = _conf_correct(pairs)
        m[key] = {
            "n": len(pairs),
            "accuracy": statistics.mean(ok for _, ok in cc) if cc else float("nan"),
            "brier": brier(pairs),
            "ece": ece(cc)[0],
        }

    mapped = [(lab, r) for lab, r in rows if lab.get("is_a11y_bug") == "1" and lab.get("criterion")]
    g_pairs = [(r["guideline_p"], r["guideline"] == lab["criterion"].rsplit(".", 1)[0]) for lab, r in mapped]
    c_pairs = [(r["criterion_p"], r["criterion"] == lab["criterion"]) for lab, r in mapped]
    g_ece, _ = ece(g_pairs)
    c_ece, c_table = ece(c_pairs)
    m["guideline"] = {"n": len(g_pairs), "accuracy": _acc(g_pairs), "ece": g_ece}
    m["criterion"] = {"n": len(c_pairs), "accuracy": _acc(c_pairs), "ece": c_ece, "reliability": c_table}

    m["selective"] = []
    for t in THRESHOLDS:
        kept = [ok for p, ok in c_pairs if p >= t]
        m["selective"].append({
            "threshold": t,
            "coverage": len(kept) / len(c_pairs) if c_pairs else float("nan"),
            "accuracy": statistics.mean(kept) if kept else float("nan"),
        })

    sev = [(r["severity"], int(lab["severity"])) for lab, r in rows if lab.get("severity") not in ("", None)]
    m["severity"] = {
        "n": len(sev),
        "mae": statistics.mean(abs(p - y) for p, y in sev) if sev else float("nan"),
        "exact": statistics.mean(round(p) == y for p, y in sev) if sev else float("nan"),
    }

    routes = [r["route"] for _, r in rows]
    auto_wrong = [lab["id"] for lab, r in mapped if r["route"] == "auto" and r["criterion"] != lab["criterion"]]
    wrongly_dismissed = [lab["id"] for lab, r in rows if r["route"] == "not_a11y" and lab.get("is_a11y_bug") == "1"]
    m["routing"] = {
        "counts": {k: routes.count(k) for k in ("auto", "expert_review", "not_a11y")},
        "auto_but_wrong_criterion": auto_wrong,
        "real_bugs_marked_not_a11y": wrongly_dismissed,
    }

    lat = sorted(r["latency_s"] for _, r in rows)
    m["usage"] = {
        "input_tokens": sum(r["input_tokens"] for _, r in rows),
        "cost_usd": sum(r["cost_usd"] for _, r in rows),
        "latency_p50_ms": 1000 * lat[len(lat) // 2] if lat else 0,
        "latency_p95_ms": 1000 * lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0,
    }
    return m


def _acc(pairs):
    return statistics.mean(ok for _, ok in pairs) if pairs else float("nan")

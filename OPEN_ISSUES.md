# Open issues

## 1. OpenJev backend (blocked on compute)

[OpenJev](https://huggingface.co/openjev/openjev) is an independent open-weights
System One model (27B, same Choice/Score/Noul primitives; not affiliated with TypeSafe).

- **Blocked on:** GPU access. Needs ~29GB for FP8 (one A100 80GB is comfortable);
  won't fit on a 16GB laptop. Asked a friend about an LTI cluster with A100s.
- **Work when unblocked:**
  - Serve with vLLM per the model card. It uses `--trust-remote-code`: read that code before running.
  - Add `OpenJevBackend` in `triage/backends.py` returning the same `Reply`; nothing else changes.
  - Run `python -m triage.run_eval --backend openjev` and add it to the comparison table.
- **Already handled:** two-stage WCAG questions keep every Choice under OpenJev's 52-option cap.
- **Before any production use:** the license is CC BY-NC 4.0. Fine for this evaluation, but the
  marketplace is commercial, so deployment would likely need a commercial license from Loop AI.
  Raise with Sunish.
- **Upside worth testing later:** it accepts one screenshot per request, which matters for Project 4.

## 2. Expert label validation

Waiting on Sunish or someone he recommends to spot-check `data/expert_review.csv`.
Report agreement rate alongside model results.

## 3. Collector bias

GitHub a11y issues skew toward developer-written web tickets. Real marketplace intake
(tester findings, client requests) will look different; swap in real data when available.

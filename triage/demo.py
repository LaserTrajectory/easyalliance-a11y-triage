"""Triage a single free-text report, for live demos.

    python -m triage.demo "VoiceOver reads the submit button as 'button' with no name"
    python -m triage.demo --backend jev "Focus disappears after closing the cookie dialog"
"""

import argparse

from triage import backends
from triage.pipeline import describe, triage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--title", default="")
    ap.add_argument("--backend", choices=["mock", "jev", "adapter"], default="mock")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    args = ap.parse_args()

    backend = backends.make(args.backend, args.provider, args.model)
    t = triage({"title": args.title, "body": args.report}, backend)
    print(f"\n[{backend.name}]" + ("  (keyword heuristics, not a model)" if args.backend == "mock" else ""))
    print(describe(t))


if __name__ == "__main__":
    main()

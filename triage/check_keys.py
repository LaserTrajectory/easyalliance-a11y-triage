"""Check which API keys are configured, and optionally that they work.

    python -m triage.check_keys                 # which keys are set (free, no network)
    python -m triage.check_keys --live          # + one tiny Jev call (a fraction of a cent)
    python -m triage.check_keys --live --provider anthropic --model claude-haiku-4-5-20251001

Key values are never printed.
"""

import argparse

from typesafe_sdk import Noul

from triage import backends, env

PROBE_STATE = {"report": "The submit button has no accessible name, so screen readers just say 'button'."}
PROBE_QUESTIONS = {"is_a11y": Noul(instructions="Does this describe an accessibility barrier?")}


def live_check(label: str, backend: backends.Backend) -> bool:
    try:
        reply = backend.ask(PROBE_STATE, PROBE_QUESTIONS)
    except Exception as e:
        reason = "key was rejected" if env.is_auth_error(e) else f"{type(e).__name__}: {str(e)[:160]}"
        print(f"  FAIL  {label}: {reason}")
        return False
    p = reply.answers["is_a11y"].value
    print(
        f"  ok    {label}: answered P(yes)={p:.2f} in {reply.latency_s * 1000:.0f} ms, "
        f"{reply.input_tokens} input tokens, ${reply.cost_usd:.6f}"
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="make one tiny call to confirm the keys work")
    ap.add_argument("--provider", choices=["openai", "anthropic", "gemini"], help="also live-check this LLM provider")
    ap.add_argument("--model", help="model for the LLM live check")
    args = ap.parse_args()

    env.load_dotenv()
    print(f".env file: {'found' if env.ENV_FILE.exists() else 'not found (copy .env.example to .env)'}")
    for name, names in env.REQUIRED.items():
        print(f"  {'set    ' if env.is_set(names) else 'missing'}  {name:<9} ({' or '.join(names)})")

    if not args.live:
        print("\nKeys only checked for presence. Add --live to confirm Jev accepts yours.")
        return

    print("\nLive check:")
    ok = True
    if env.is_set(env.REQUIRED["jev"]):
        ok &= live_check("jev", backends.make("jev"))
    else:
        print("  skip  jev: TYPESAFE_API_KEY not set")
        ok = False
    if args.provider:
        if not args.model:
            raise SystemExit("--provider needs --model for the live check")
        ok &= live_check(args.provider, backends.make("adapter", args.provider, args.model))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

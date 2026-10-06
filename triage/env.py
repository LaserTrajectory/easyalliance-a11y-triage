"""API key handling: load .env, and fail with a clear message when a key is missing.

Keys are only ever reported as set or missing; their values are never printed.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Environment variables each backend reads. Any one of a tuple is enough.
REQUIRED = {
    "jev": ("TYPESAFE_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines from .env. Variables already set in the shell win; blank values are skipped."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if value and key not in os.environ:
            os.environ[key] = value


def is_set(names: tuple[str, ...]) -> bool:
    return any(os.environ.get(n) for n in names)


def require(name: str) -> None:
    """Exit with setup instructions if the keys for backend/provider `name` are missing."""
    names = REQUIRED[name]
    if is_set(names):
        return
    step = "Add it to .env" if ENV_FILE.exists() else "Copy .env.example to .env and add it there"
    raise SystemExit(
        f"Missing API key for {name}: set {' or '.join(names)}.\n"
        f"  {step}, then check with: .venv/bin/python -m triage.check_keys"
    )


def is_auth_error(e: Exception) -> bool:
    """True for a rejected key from TypeSafe or any LLM provider SDK."""
    return any("Authentication" in cls.__name__ or "PermissionDenied" in cls.__name__ for cls in type(e).__mro__)

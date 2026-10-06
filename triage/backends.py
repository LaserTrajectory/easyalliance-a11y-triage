"""Interchangeable backends that answer System One questions.

Every backend returns the same normalized `Reply`, so the pipeline and the
metrics never know which model answered. Adding OpenJev later means adding
one class here (see OPEN_ISSUES.md).

    mock     keyword heuristics, offline, free; for demos and plumbing tests only
    jev      TypeSafe's hosted Jev (needs TYPESAFE_API_KEY and credits)
    adapter  any LLM via TypeSafe's system-one-adapter (needs that provider's API key)
"""

import json
import re
import time
from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, Score

from triage import env

JEV_USD_PER_MTOK = 0.042  # input only; output tokens are free (docs.typesafe.ai/models)


@dataclass
class Answer:
    type: str  # "choice" | "score" | "noul"
    value: str | float  # choice name, expected score, or P(yes)
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass
class Reply:
    answers: dict[str, Answer]
    input_tokens: int
    latency_s: float
    cost_usd: float


def estimate_tokens(state: dict, questions: dict) -> int:
    """Rough pre-flight estimate (~4 chars/token) used for budget checks."""
    text = json.dumps(state) + json.dumps({k: q.model_dump() for k, q in questions.items()}, default=str)
    return len(text) // 4


def _normalize(raw) -> dict[str, Answer]:
    out = {}
    for name, a in raw.answers.items():
        probs = {str(k): float(v) for k, v in (getattr(a, "probabilities", None) or {}).items()}
        if a.type == "choice":
            out[name] = Answer("choice", a.choice, probs, a.confidence)
        elif a.type == "score":
            out[name] = Answer("score", float(a.score), probs, a.confidence)
        else:
            p = float(a.noul)
            out[name] = Answer("noul", p, {"true": p, "false": 1 - p}, max(p, 1 - p))
    return out


class Backend:
    name = "base"

    def ask(self, state: dict, questions: dict) -> Reply:
        raise NotImplementedError


class JevBackend(Backend):
    def __init__(self, model: str = "jev-latest"):
        from typesafe_sdk import TypeSafeClient

        self.client = TypeSafeClient(model=model)
        self.name = f"jev:{model}"

    def ask(self, state, questions):
        t0 = time.perf_counter()
        raw = self.client.system_one(state=state, questions=questions)
        latency = time.perf_counter() - t0
        tokens = raw.usage.input_tokens
        return Reply(_normalize(raw), tokens, latency, tokens * JEV_USD_PER_MTOK / 1e6)


class AdapterBackend(Backend):
    def __init__(self, provider: str, model: str, usd_per_mtok: float = 0.0):
        from system_one_adapter import SystemOneAdapterClient

        self.client = SystemOneAdapterClient(
            structured_outputs=True, llm_answer_mode="probabilities", normalize_probabilities=True
        )
        self.provider, self.model, self.usd_per_mtok = provider, model, usd_per_mtok
        self.name = f"{provider}:{model}"

    def ask(self, state, questions):
        t0 = time.perf_counter()
        raw = self.client.system_one(state=state, questions=questions, provider=self.provider, model=self.model)
        latency = time.perf_counter() - t0
        tokens = getattr(raw.usage, "input_tokens", 0) or 0
        # Output tokens are billed for LLMs; pass a blended --usd-per-mtok to approximate.
        return Reply(_normalize(raw), tokens, latency, tokens * self.usd_per_mtok / 1e6)


# --- mock -------------------------------------------------------------------

# Guideline / criterion hints by keyword. Deliberately crude: this exists so the
# whole pipeline runs offline, not to be a baseline anyone should cite.
_HINTS = [
    (r"alt[ -]?text|\balt\b|image|icon|svg|non-text", "1.1", "1.1.1"),
    (r"caption|subtitle|transcript|audio description|video", "1.2", "1.2.2"),
    (r"heading|landmark|table header|semantic|reading order|label.*(input|field)", "1.3", "1.3.1"),
    (r"contrast|colou?r|zoom|reflow|resize|text spacing", "1.4", "1.4.3"),
    (r"keyboard|tab key|trap|shortcut", "2.1", "2.1.1"),
    (r"timeout|time limit|auto-?play|carousel|pause", "2.2", "2.2.2"),
    (r"flash|seizure|animation|motion", "2.3", "2.3.3"),
    (r"focus|skip link|link text|page title|tab order", "2.4", "2.4.7"),
    (r"touch target|drag|pointer|gesture|target size", "2.5", "2.5.8"),
    (r"\blang\b|language|jargon", "3.1", "3.1.1"),
    (r"unexpected|context change|navigation order|consistent", "3.2", "3.2.2"),
    (r"error message|validation|form error|required field", "3.3", "3.3.1"),
    (r"aria|screen ?reader|voiceover|nvda|jaws|talkback|announce|accessible name|role", "4.1", "4.1.2"),
]
_BLOCKING = re.compile(r"cannot|can't|unable|impossible|blocks?|stuck|trap", re.I)
_REPRO = re.compile(r"steps to reproduce|repro|1\.\s|expected|actual|version", re.I)


class MockBackend(Backend):
    name = "mock"

    def ask(self, state, questions):
        text = f"{state.get('title', '')} {state.get('report', '')}".lower()
        hits = [(g, sc) for pat, g, sc in _HINTS if re.search(pat, text)]
        answers = {}
        for name, q in questions.items():
            if isinstance(q, Noul):
                if name == "has_repro":
                    p = 0.85 if _REPRO.search(text) else 0.25
                else:
                    p = 0.9 if hits else 0.2
                answers[name] = Answer("noul", p, {"true": p, "false": 1 - p}, max(p, 1 - p))
            elif isinstance(q, Choice):
                options = list(q.criteria)
                votes = [sc if name == "criterion" else g for g, sc in hits]
                votes = [v for v in votes if v in options] or [options[-1]]
                probs = {o: 0.02 for o in options}
                for v in votes:
                    probs[v] += 1.0 / len(votes)
                total = sum(probs.values())
                probs = {o: p / total for o, p in probs.items()}
                best = max(probs, key=probs.get)
                answers[name] = Answer("choice", best, probs, probs[best])
            elif isinstance(q, Score):
                level = 2 if _BLOCKING.search(text) else 1
                probs = {str(i): (0.7 if i == level else 0.15) for i in range(len(q.criteria))}
                answers[name] = Answer("score", float(level), probs, 0.7)
        return Reply(answers, estimate_tokens(state, questions), 0.0, 0.0)


def make(kind: str, provider: str | None = None, model: str | None = None, usd_per_mtok: float = 0.0) -> Backend:
    if kind == "mock":
        return MockBackend()
    env.load_dotenv()
    if kind == "jev":
        env.require("jev")
        return JevBackend(model or "jev-latest")
    if kind == "adapter":
        if not (provider and model):
            raise SystemExit("--backend adapter needs --provider and --model")
        env.require(provider)
        return AdapterBackend(provider, model, usd_per_mtok)
    raise SystemExit(f"unknown backend {kind!r}")

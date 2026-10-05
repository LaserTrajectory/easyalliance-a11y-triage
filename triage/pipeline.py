"""Triage one accessibility report: two model calls, then plain code decides.

The model only answers narrow questions. Everything after that (combining
stages, routing to a human) is deterministic and lives here, where it can be
read, tested and argued about.
"""

from dataclasses import asdict, dataclass, field

from triage import questions, wcag
from triage.backends import Backend

# Routing policy. These are placeholders: the eval report's coverage/accuracy
# table is how the real values should be chosen.
AUTO_CONFIDENCE = 0.80  # joint P(guideline) * P(criterion | guideline)
ALWAYS_REVIEW_SEVERITY = 1.5  # blocking-leaning issues always get human eyes


@dataclass
class Triage:
    is_a11y_bug: float
    guideline: str
    guideline_p: float
    criterion: str | None
    criterion_p: float  # joint probability, comparable across guidelines
    severity: float
    has_repro: float
    route: str  # "auto" | "expert_review" | "not_a11y"
    reasons: list[str] = field(default_factory=list)
    input_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def triage(issue: dict, backend: Backend) -> Triage:
    state = questions.state(issue)

    r1 = backend.ask(state, questions.stage1())
    a = r1.answers
    guideline = a["guideline"].value
    g_p = a["guideline"].probabilities.get(guideline, a["guideline"].confidence or 0.0)
    tokens, latency, cost = r1.input_tokens, r1.latency_s, r1.cost_usd

    criterion, c_p = None, 0.0
    if guideline != questions.NOT_WCAG:
        r2 = backend.ask(state, questions.stage2(guideline))
        c = r2.answers["criterion"]
        criterion = c.value
        c_p = g_p * c.probabilities.get(criterion, c.confidence or 0.0)
        tokens, latency, cost = tokens + r2.input_tokens, latency + r2.latency_s, cost + r2.cost_usd

    t = Triage(
        is_a11y_bug=a["is_a11y_bug"].value,
        guideline=guideline,
        guideline_p=g_p,
        criterion=criterion,
        criterion_p=c_p,
        severity=a["severity"].value,
        has_repro=a["has_repro"].value,
        route="auto",
        input_tokens=tokens,
        latency_s=latency,
        cost_usd=cost,
    )
    return route(t)


def route(t: Triage) -> Triage:
    if t.is_a11y_bug < 0.5 or t.guideline == questions.NOT_WCAG:
        t.route = "not_a11y"
        t.reasons.append("model judged this is not a WCAG barrier; a human should confirm before closing")
        return t
    if t.criterion_p < AUTO_CONFIDENCE:
        t.reasons.append(f"WCAG mapping confidence {t.criterion_p:.2f} < {AUTO_CONFIDENCE}")
    if t.severity >= ALWAYS_REVIEW_SEVERITY:
        t.reasons.append(f"severity {t.severity:.1f} is blocking-leaning")
    if t.has_repro < 0.5:
        t.reasons.append("report may lack reproduction detail; ask the tester for more")
    if t.reasons:
        t.route = "expert_review"
    return t


def describe(t: Triage) -> str:
    sc = wcag.criterion(t.criterion) if t.criterion else None
    lines = [
        f"  route        {t.route.upper()}",
        f"  a11y bug     P={t.is_a11y_bug:.2f}",
        f"  guideline    {t.guideline}"
        + (f" {wcag.guideline(t.guideline)['handle']}" if t.guideline != questions.NOT_WCAG else "")
        + f"  (P={t.guideline_p:.2f})",
    ]
    if sc:
        lines.append(f"  criterion    {sc['num']} {sc['handle']} (Level {sc['level']})  (joint P={t.criterion_p:.2f})")
    lines += [
        f"  severity     {t.severity:.2f} / 2  ({questions.SEVERITY_LEVELS[round(t.severity)].split(':')[0]})",
        f"  has repro    P={t.has_repro:.2f}",
    ]
    lines += [f"  why review:  {r}" for r in t.reasons]
    lines.append(f"  usage        {t.input_tokens} input tokens, {t.latency_s * 1000:.0f} ms, ${t.cost_usd:.6f}")
    return "\n".join(lines)

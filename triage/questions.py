"""The triage questions, written once and sent unchanged to every backend.

WCAG mapping is split into two stages because no single Choice should hold all
86 criteria (OpenJev caps a Choice at 52 options; Jev at 255) and because the
TypeSafe docs recommend narrow, decomposed questions:

    stage 1: is it an a11y bug? which of 13 guidelines? how severe? has repro?
    stage 2: which success criterion within the chosen guideline (<= 13 options)?
"""

from typesafe_sdk import Choice, Noul, Score

from triage import wcag

NOT_WCAG = "none"

SEVERITY_LEVELS = [
    "Minor: cosmetic or annoying, but every user can still complete the task.",
    "Moderate: some users need a workaround or extra effort to complete the task.",
    "Blocking: some disabled users cannot complete the task at all.",
]


def stage1() -> dict:
    guideline_options = {g["num"]: f"{g['handle']}: {g['text']}" for g in wcag.guidelines()}
    guideline_options[NOT_WCAG] = (
        "Not a WCAG conformance problem: feature request, question, docs, tooling or test infrastructure."
    )
    return {
        "is_a11y_bug": Noul(
            instructions="Does this report describe an accessibility barrier that users with disabilities "
            "experience in the product (not a feature request, question or internal tooling task)?"
        ),
        "guideline": Choice(
            instructions="Which WCAG 2.2 guideline does the reported barrier fall under?",
            criteria=guideline_options,
        ),
        "severity": Score(
            instructions="How severely does this barrier affect users with disabilities?",
            criteria=SEVERITY_LEVELS,
        ),
        "has_repro": Noul(
            instructions="Does the report give enough steps, environment or assistive-technology detail "
            "for a tester to reproduce the problem?"
        ),
    }


def stage2(guideline_num: str) -> dict:
    g = wcag.guideline(guideline_num)
    return {
        "criterion": Choice(
            instructions=f"Within WCAG 2.2 guideline {g['num']} ({g['handle']}), which success criterion "
            "does the reported barrier fail?",
            criteria={sc["num"]: f"{sc['handle']} (Level {sc['level']}): {sc['text']}" for sc in g["criteria"]},
        )
    }


def state(issue: dict) -> dict:
    """Only what the model needs: no URLs, authors or repo metadata."""
    return {"title": issue["title"], "report": issue["body"]}

"""Fail-closed release gate for deterministic evaluation scores."""

from __future__ import annotations

from collections.abc import Iterable

from app.evals.contracts import GateResult, ScoreResult


def evaluate_gate(
    scores: Iterable[ScoreResult],
    *,
    fail_on_any_p0: bool,
    minimum_p1_score: float,
) -> GateResult:
    values = list(scores)
    required_incomplete = [score for score in values if score.hard_gate and score.status == "incomplete"]
    p0_failures = [score for score in values if score.priority == "P0" and score.status == "failed"]
    p1_values = [score.score for score in values if score.priority == "P1" and score.status != "incomplete" and score.score is not None]
    p1_score = sum(p1_values) / len(p1_values) if p1_values else None

    reason_codes: list[str] = []
    if p0_failures:
        reason_codes.extend(score.reason_code for score in p0_failures)
        status = "failed"
    elif required_incomplete:
        reason_codes.extend(score.reason_code for score in required_incomplete)
        status = "incomplete"
    elif p1_score is not None and p1_score < minimum_p1_score:
        reason_codes.append("P1_SCORE_BELOW_THRESHOLD")
        status = "failed"
    else:
        status = "passed"

    return GateResult(
        status=status,
        passed=status == "passed",
        p0_failures=len(p0_failures),
        incomplete_required=len(required_incomplete),
        p1_score=p1_score,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )

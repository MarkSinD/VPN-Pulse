from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import Evaluation, Observation, ObservationResult, ServerCandidate, State


SUCCESS_SOURCES = {"human_activity", "pc"}


def _valid_full_failure(item: Observation) -> bool:
    return (
        item.result is ObservationResult.FAILURE
        and item.full_vpn_test
        and item.control_internet_ok is True
    )


def evaluate_scope(
    observations: Iterable[Observation],
    *,
    now: datetime,
    expected_sources: int = 1,
    failure_confirmations: int = 2,
) -> Evaluation:
    """Evaluate one server/protocol/network scope using fresh evidence only.

    Absence of human activity and a stopped probe never become failure. A confirmed
    unavailable state requires consecutive valid full-test failures with working
    control Internet. Conflicting success/failure evidence is degraded.
    """

    items = sorted(observations, key=lambda item: item.observed_at)
    fresh = [item for item in items if item.fresh_until >= now]
    coverage = min(1.0, len({item.source for item in fresh}) / max(expected_sources, 1))
    if not fresh:
        return Evaluation(State.UNKNOWN, "NO_FRESH_EVIDENCE", None, None, 0, coverage)

    latest_at = max(item.observed_at for item in fresh)
    fresh_until = max(item.fresh_until for item in fresh)
    valid_successes = [
        item
        for item in fresh
        if item.result is ObservationResult.SUCCESS
        and (item.source == "human_activity" or item.full_vpn_test)
    ]
    partial_failures = [item for item in fresh if item.result is ObservationResult.FAILURE]

    full_by_source: dict[str, list[Observation]] = {}
    for item in fresh:
        if item.full_vpn_test:
            full_by_source.setdefault(item.source, []).append(item)

    confirmed_failure = False
    for source_items in full_by_source.values():
        tail = source_items[-failure_confirmations:]
        if len(tail) == failure_confirmations and all(_valid_full_failure(item) for item in tail):
            confirmed_failure = True
            break

    if valid_successes and partial_failures:
        state, reason = State.DEGRADED, "CONFLICTING_FRESH_EVIDENCE"
    elif confirmed_failure:
        state, reason = State.UNAVAILABLE, "FULL_TEST_FAILURE_CONFIRMED"
    elif valid_successes:
        state, reason = State.OPERATIONAL, "FULL_SUCCESS_CONFIRMED"
    elif partial_failures:
        state, reason = State.DEGRADED, "PARTIAL_OR_UNCONFIRMED_FAILURE"
    else:
        state, reason = State.UNKNOWN, "NO_CONCLUSIVE_EVIDENCE"

    return Evaluation(state, reason, latest_at, fresh_until, len(fresh), coverage)


def recommend_server(
    candidates: Iterable[ServerCandidate], *, previous_server_id: str | None = None
) -> str | None:
    """Choose a stable operational server without pretending incomplete load is known."""

    eligible = [
        item
        for item in candidates
        if item.evaluation.state is State.OPERATIONAL
        and item.evaluation.coverage > 0
        and item.complete_protocol_coverage
    ]
    if not eligible:
        return None

    previous = next((item for item in eligible if item.server_id == previous_server_id), None)
    ranked = sorted(
        eligible,
        key=lambda item: (
            item.load_score is None,
            item.load_score if item.load_score is not None else float("inf"),
            -item.priority,
            item.server_id,
        ),
    )
    best = ranked[0]
    if previous is not None:
        if previous.load_score is None or best.load_score is None:
            return previous.server_id
        if previous.load_score <= best.load_score * 1.10:
            return previous.server_id
    return best.server_id

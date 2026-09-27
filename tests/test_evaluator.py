import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vpnpulse.domain import (
    Evaluation,
    Observation,
    ObservationResult,
    ServerCandidate,
    State,
    evaluate_scope,
    recommend_server,
)


NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
SCENARIOS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "scenarios.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_canonical_scenarios(scenario):
    observations = [
        Observation(
            source=item["source"],
            result=ObservationResult(item["result"]),
            observed_at=NOW - timedelta(seconds=item["age"]),
            fresh_until=NOW - timedelta(seconds=item["age"]) + timedelta(seconds=180),
            full_vpn_test=item["full"],
            control_internet_ok=item["control"],
        )
        for item in scenario["observations"]
    ]
    result = evaluate_scope(observations, now=NOW)
    assert result.state is State(scenario["expected"])


def candidate(server_id, state, load, coverage=True, priority=0):
    evaluation = Evaluation(state, "TEST", NOW, NOW + timedelta(seconds=180), 1, 1.0)
    return ServerCandidate(server_id, evaluation, load, coverage, priority)


def test_recommendation_excludes_unknown_and_incomplete_protocol_coverage():
    result = recommend_server(
        [
            candidate("server-1", State.UNKNOWN, 1),
            candidate("server-2", State.OPERATIONAL, 1, coverage=False),
            candidate("server-3", State.OPERATIONAL, 3),
        ]
    )
    assert result == "server-3"


def test_recommendation_is_stable_within_ten_percent():
    result = recommend_server(
        [candidate("server-1", State.OPERATIONAL, 10), candidate("server-2", State.OPERATIONAL, 9.5)],
        previous_server_id="server-1",
    )
    assert result == "server-1"



def observation(source, result, age, *, full=False, control=None):
    at = NOW - timedelta(seconds=age)
    return Observation(source=source, result=ObservationResult(result), observed_at=at,
                       fresh_until=at + timedelta(seconds=180), full_vpn_test=full, control_internet_ok=control)


def test_a_cross_server_handshake_is_evidence_that_the_tunnel_answers():
    """A server whose people are idle must not read as «no fresh data» while probes reach it."""
    # the collector knows the host is alive, but that is not a test of the tunnel
    collector_only = [observation("collector", "success", 10)]
    assert evaluate_scope(collector_only, now=NOW).state is State.UNKNOWN

    # add a cross-server handshake: someone outside just came through the tunnel
    with_abroad = collector_only + [observation("abroad", "success", 30)]
    assert evaluate_scope(with_abroad, now=NOW).state is State.OPERATIONAL

    # a failing probe still drags the state down, as before — both sides of its evidence count
    conflicting = with_abroad + [observation("abroad", "failure", 5)]
    assert evaluate_scope(conflicting, now=NOW).state is State.DEGRADED

    # blocked where the members are, alive from abroad: that is still an outage for the members, and
    # the succeeding probe must not talk it down to "some problems"
    outage = [observation("pc", "failure", age, full=True, control=True) for age in (60, 10)]
    assert evaluate_scope(outage + [observation("abroad", "success", 20)], now=NOW).state is State.UNAVAILABLE
    # people who are actually connected do contradict it - they sit where the members sit
    assert evaluate_scope(outage + [observation("human_activity", "success", 20)], now=NOW).state is State.DEGRADED

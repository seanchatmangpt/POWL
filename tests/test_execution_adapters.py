"""Real tests for powl.execution.adapters.bindings.replay_with_bindings --
no mocks: real TaggedPOWL models, real action_bindings callables that
mutate a real shared list, a real hand-written EvidenceRecorder, a real
raised exception from a real binding, and a real wall-clock timing proof
of concurrent binding invocation (same technique as
test_execution_concurrent.py's Phase-1-Concurrent test).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

import pytest

from powl.execution.adapters.bindings import replay_with_bindings
from powl.execution.adapters.evidence import EvidenceRecorder
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.base import TaggedPOWL
from powl.objects.tagged_powl.partial_order import PartialOrder


def _first_only_chooser(node, options):
    return options[0]


def _never_repeat(node, completed):
    return False


class InMemoryRecorder:
    """A real, hand-written EvidenceRecorder: no OCEL, no mock -- real
    accumulated state in a plain list, satisfying the EvidenceRecorder
    Protocol structurally (see adapters/evidence.py)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, TaggedPOWL, Mapping[str, Any]]] = []

    def record(self, activity: str, node: TaggedPOWL, outcome: Mapping[str, Any]) -> None:
        self.calls.append((activity, node, dict(outcome)))


def test_satisfies_evidence_recorder_protocol_structurally():
    assert isinstance(InMemoryRecorder(), EvidenceRecorder)


def test_bound_activities_invoked_exactly_once_unbound_absent():
    a = Activity(label="a")
    b = Activity(label="b")
    c = Activity(label="c")  # deliberately left unbound
    model = PartialOrder(nodes=[a, b, c], edges=[(a, b), (b, c)])

    invocations: list[tuple[str, int]] = []

    def bind_a(node: TaggedPOWL) -> None:
        invocations.append((node.label, threading.get_ident()))

    def bind_b(node: TaggedPOWL) -> None:
        invocations.append((node.label, threading.get_ident()))

    steps = replay_with_bindings(
        model,
        chooser=_first_only_chooser,
        repeat_decider=_never_repeat,
        action_bindings={"a": bind_a, "b": bind_b},
    )

    assert [s.node.label for s in steps] == ["a", "b", "c"]
    labels_invoked = [label for label, _ in invocations]
    assert sorted(labels_invoked) == ["a", "b"]
    assert "c" not in labels_invoked
    # each bound activity invoked exactly once
    assert labels_invoked.count("a") == 1
    assert labels_invoked.count("b") == 1


def test_recorder_receives_a_call_for_every_fired_step_with_correct_outcomes():
    a = Activity(label="a")
    b = Activity(label="b")
    model = PartialOrder(nodes=[a, b], edges=[(a, b)])

    def bind_a(node: TaggedPOWL) -> str:
        return "did-a"

    recorder = InMemoryRecorder()
    steps = replay_with_bindings(
        model,
        chooser=_first_only_chooser,
        repeat_decider=_never_repeat,
        action_bindings={"a": bind_a},
        recorder=recorder,
    )

    assert len(recorder.calls) == len(steps) == 2

    activity_a, node_a, outcome_a = recorder.calls[0]
    assert activity_a == "a"
    assert node_a is a
    assert outcome_a == {"status": "success", "result": "did-a"}

    activity_b, node_b, outcome_b = recorder.calls[1]
    assert activity_b == "b"
    assert node_b is b
    assert outcome_b == {"status": "unbound"}


def test_raising_binding_reraises_and_recorder_still_gets_error_outcome_first():
    a = Activity(label="a")
    b = Activity(label="b")
    model = PartialOrder(nodes=[a, b], edges=[(a, b)])

    class BoomError(RuntimeError):
        pass

    def bind_a(node: TaggedPOWL) -> None:
        raise BoomError("real failure from a real binding")

    recorder = InMemoryRecorder()

    with pytest.raises(BoomError, match="real failure from a real binding"):
        replay_with_bindings(
            model,
            chooser=_first_only_chooser,
            repeat_decider=_never_repeat,
            action_bindings={"a": bind_a},
            recorder=recorder,
        )

    # Proof the (c)-then-raise ordering is real: the recorder's real
    # accumulated state, inspected AFTER the real exception was caught,
    # shows it received records for BOTH real fired steps (including the
    # failing one, with a real error outcome) before the exception
    # propagated out of replay_with_bindings.
    assert len(recorder.calls) == 2
    activity_a, node_a, outcome_a = recorder.calls[0]
    assert activity_a == "a"
    assert node_a is a
    assert outcome_a["status"] == "error"
    assert isinstance(outcome_a["error"], BoomError)

    activity_b, node_b, outcome_b = recorder.calls[1]
    assert activity_b == "b"
    assert outcome_b == {"status": "unbound"}


def test_bindings_invoked_concurrently_not_sequentially():
    n = 4
    delay_s = 0.08
    activities = [Activity(label=f"a{i}") for i in range(n)]
    # No edges: a single real topological generation of n independent
    # siblings inside the PartialOrder (structural firing order is not
    # what's being timed here -- binding invocation is).
    model = PartialOrder(nodes=activities, edges=[])

    timings: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    def make_binding(label: str):
        def binding(node: TaggedPOWL) -> None:
            start = time.monotonic()
            time.sleep(delay_s)
            end = time.monotonic()
            with lock:
                timings.append((label, start, end))

        return binding

    action_bindings = {f"a{i}": make_binding(f"a{i}") for i in range(n)}

    started = time.monotonic()
    steps = replay_with_bindings(
        model,
        chooser=_first_only_chooser,
        repeat_decider=_never_repeat,
        action_bindings=action_bindings,
    )
    elapsed = time.monotonic() - started

    assert len(steps) == n
    assert len(timings) == n

    # Real concurrency proof: n bindings each with a real delay_s sleep.
    # Sequential invocation would take ~n*delay_s; concurrent invocation
    # takes ~delay_s. Generous margin, well under n*delay_s.
    assert elapsed < delay_s * (n / 2)

    # A second, independent concurrency signal: the recorded sleeps
    # genuinely overlapped in wall-clock time.
    overlap_found = any(
        a_start < b_end and b_start < a_end
        for (_, a_start, a_end) in timings
        for (_, b_start, b_end) in timings
        if (a_start, a_end) != (b_start, b_end)
    )
    assert overlap_found

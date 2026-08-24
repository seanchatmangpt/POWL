from __future__ import annotations

import threading

import pytest

from powl.execution import SpiffPOWLExecutor, UnsupportedPOWLExecution
from powl.objects.tagged_powl import Activity, PartialOrder
from powl.objects.tagged_powl.builders import xor


def test_spiff_executes_the_ready_powl_frontier_concurrently() -> None:
    left = Activity("left")
    right = Activity("right")
    join = Activity("join")
    model = PartialOrder(
        nodes=[left, right, join],
        edges=[(left, join), (right, join)],
    )

    rendezvous = threading.Barrier(2, timeout=5)
    left_done = threading.Event()
    right_done = threading.Event()

    def handler(activity: Activity) -> str:
        if activity in (left, right):
            rendezvous.wait()
            if activity is left:
                left_done.set()
            else:
                right_done.set()
        elif activity is join:
            assert left_done.is_set()
            assert right_done.is_set()
        return activity.label or "tau"

    receipt = SpiffPOWLExecutor(max_workers=2).execute(model, handler)

    left_run = receipt.for_activity(left)
    right_run = receipt.for_activity(right)
    join_run = receipt.for_activity(join)

    assert left_run.started_ns < right_run.finished_ns
    assert right_run.started_ns < left_run.finished_ns
    assert left_run.thread_id != right_run.thread_id
    assert join_run.started_ns >= max(left_run.finished_ns, right_run.finished_ns)
    assert {run.result for run in receipt.executions} == {"left", "right", "join"}


def test_spiff_releases_successors_without_waiting_for_unrelated_work() -> None:
    fast = Activity("fast")
    slow = Activity("slow")
    fast_successor = Activity("fast-successor")
    model = PartialOrder(
        nodes=[fast, slow, fast_successor],
        edges=[(fast, fast_successor)],
    )

    slow_started = threading.Event()
    release_slow = threading.Event()
    successor_ran_while_slow_active = threading.Event()

    def handler(activity: Activity) -> str:
        if activity is slow:
            slow_started.set()
            assert release_slow.wait(timeout=5)
        elif activity is fast:
            assert slow_started.wait(timeout=5)
        elif activity is fast_successor:
            if slow_started.is_set() and not release_slow.is_set():
                successor_ran_while_slow_active.set()
            release_slow.set()
        return activity.label or "tau"

    receipt = SpiffPOWLExecutor(max_workers=2).execute(model, handler)

    assert successor_ran_while_slow_active.is_set()
    assert receipt.for_activity(fast_successor).finished_ns <= receipt.for_activity(slow).finished_ns


def test_spiff_does_not_reinterpret_choice_as_parallelism() -> None:
    model = xor([Activity("a"), Activity("b")])

    with pytest.raises(UnsupportedPOWLExecution, match="choice policy"):
        SpiffPOWLExecutor().execute(model, lambda activity: activity.label)


def test_spiff_requires_frequency_semantics_to_be_resolved() -> None:
    model = Activity("retry", min_freq=0, max_freq=None)

    with pytest.raises(UnsupportedPOWLExecution, match="exact-once"):
        SpiffPOWLExecutor().execute(model, lambda activity: activity.label)

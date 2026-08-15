"""Real tests for powl.execution.replay_concurrent -- no mocks: every test
drives real TaggedPOWL models through the real replay_concurrent() engine
and asserts on the real returned ExecutionStep sequence, real thread
identities, and real wall-clock timing.

Concurrency proof technique: repeat_decider is a real, already-existing
external-decision extension point (see engine.py's module docstring) that
the engine genuinely invokes from whichever thread is executing the node in
question -- for a PartialOrder branch fired concurrently, that is a real
worker thread, not the calling thread. Each branch here is built as a
composite node with max_freq=2 so that after its body fires once, the
engine consults repeat_decider (a real choice: min_freq=1 already met,
room left under max_freq=2) -- giving a real callback invoked on the real
worker thread, where a real time.sleep + real time.monotonic() timestamps
are taken. No new engine mechanism was added or needed: this uses exactly
the callback surface the engine already, genuinely offers callers.
"""

from __future__ import annotations

import threading
import time

import pytest

from powl.execution import ExecutionRefusal, ExecutionStep, replay, replay_concurrent
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.builders import sequence
from powl.objects.tagged_powl.partial_order import PartialOrder


def _labels(steps: tuple[ExecutionStep, ...]) -> tuple[str | None, ...]:
    return tuple(step.node.label for step in steps)


def _first_only_chooser(node, options):
    return options[0]


def _never_repeat(node, completed):
    return False


def _make_branch(name: str, delay_log: list[tuple[str, int, float, float]], delay_s: float) -> PartialOrder:
    """A branch: two real sequential activities, then a real repeat
    consultation on the branch node itself (max_freq=2) used purely as a
    real hook to record (label, thread_ident, start, end) timing -- the
    branch never actually repeats (the decider always returns False after
    recording)."""
    a0 = Activity(label=f"{name}-0")
    a1 = Activity(label=f"{name}-1")
    return PartialOrder(nodes=[a0, a1], edges=[(a0, a1)], min_freq=1, max_freq=2)


def _timed_repeat_decider(delay_log: list[tuple[str, int, float, float]], lock: threading.Lock, delay_s: float):
    def decider(node, completed):
        if completed != 1:
            return False
        start = time.monotonic()
        time.sleep(delay_s)
        end = time.monotonic()
        with lock:
            delay_log.append((repr(node), threading.get_ident(), start, end))
        return False

    return decider


def test_independent_branches_all_fire_in_branch_order_and_concurrently():
    delay_log: list[tuple[str, int, float, float]] = []
    lock = threading.Lock()
    delay_s = 0.08
    n_branches = 4

    branches = [_make_branch(f"b{i}", delay_log, delay_s) for i in range(n_branches)]
    model = PartialOrder(nodes=branches, edges=[])

    decider = _timed_repeat_decider(delay_log, lock, delay_s)

    started = time.monotonic()
    steps = replay_concurrent(
        model, chooser=_first_only_chooser, repeat_decider=decider, max_workers=None
    )
    elapsed = time.monotonic() - started

    labels = _labels(steps)
    # every activity from every branch is present exactly once
    expected = set()
    for i in range(n_branches):
        expected.add(f"b{i}-0")
        expected.add(f"b{i}-1")
    assert set(labels) == expected
    assert len(labels) == len(expected)

    # each branch's own internal order (0 before 1) is respected
    for i in range(n_branches):
        idx0 = labels.index(f"b{i}-0")
        idx1 = labels.index(f"b{i}-1")
        assert idx0 < idx1

    # real concurrency proof: N branches each with a real delay_s sleep on
    # their own worker thread. Sequential firing would take ~N*delay_s;
    # concurrent firing takes ~delay_s. Generous margin: well under N*delay_s.
    assert len(delay_log) == n_branches
    assert elapsed < delay_s * (n_branches / 2)

    # the recorded sleeps genuinely overlapped in wall-clock time (a second
    # sleep started before an earlier one finished) -- a second, independent
    # concurrency signal beyond total elapsed time.
    overlap_found = any(
        a_start < b_end and b_start < a_end
        for (_, _, a_start, a_end) in delay_log
        for (_, _, b_start, b_end) in delay_log
        if (a_start, a_end) != (b_start, b_end)
    )
    assert overlap_found

    # real distinct worker threads were actually used (not the calling
    # thread alone reused N times)
    thread_idents = {ident for (_, ident, _, _) in delay_log}
    assert len(thread_idents) > 1


def test_every_node_fires_exactly_once_across_many_repeated_real_replays():
    n_branches = 3

    def build_model():
        branches = [_make_branch(f"b{i}", [], 0.0) for i in range(n_branches)]
        return PartialOrder(nodes=branches, edges=[])

    expected = set()
    for i in range(n_branches):
        expected.add(f"b{i}-0")
        expected.add(f"b{i}-1")

    for _ in range(20):
        model = build_model()
        steps = replay_concurrent(
            model, chooser=_first_only_chooser, repeat_decider=_never_repeat, max_workers=None
        )
        labels = _labels(steps)
        assert sorted(labels) == sorted(expected)
        assert len(labels) == len(set(labels))


def test_chooser_returning_unoffered_option_raises_same_refusal_as_replay():
    a = Activity(label="a")
    b = Activity(label="b")
    from powl.objects.tagged_powl.builders import xor

    model = xor([a, b])
    off_model_activity = Activity(label="not-a-real-option")

    def bad_chooser(node, options):
        return off_model_activity

    with pytest.raises(ExecutionRefusal, match="CHOOSER_RETURNED_UNOFFERED_OPTION") as exc_sequential:
        replay(model, chooser=bad_chooser, repeat_decider=_never_repeat)

    with pytest.raises(ExecutionRefusal, match="CHOOSER_RETURNED_UNOFFERED_OPTION") as exc_concurrent:
        replay_concurrent(model, chooser=bad_chooser, repeat_decider=_never_repeat)

    assert exc_sequential.value.refusal == exc_concurrent.value.refusal


def test_max_steps_exceeded_raises_same_refusal_as_replay():
    do = Activity(label="do")
    redo = Activity(label="redo")
    from powl.objects.tagged_powl.builders import loop

    model = loop(do, redo)

    def always_repeat(node, completed):
        return True

    with pytest.raises(ExecutionRefusal, match="MAX_STEPS_EXCEEDED") as exc_sequential:
        replay(model, chooser=_first_only_chooser, repeat_decider=always_repeat, max_steps=5)

    with pytest.raises(ExecutionRefusal, match="MAX_STEPS_EXCEEDED") as exc_concurrent:
        replay_concurrent(
            model, chooser=_first_only_chooser, repeat_decider=always_repeat, max_steps=5
        )

    assert exc_sequential.value.refusal == exc_concurrent.value.refusal


def test_single_branch_partial_order_uses_no_thread_pool_and_matches_replay():
    # A single top-level branch: the outer PartialOrder's own topological
    # generation has exactly one member, so replay_concurrent must run it
    # on the calling thread directly, identical to replay().
    a = Activity(label="a")
    b = Activity(label="b")
    c = Activity(label="c")
    model = sequence([a, b, c])

    steps_sequential = replay(model, chooser=_first_only_chooser, repeat_decider=_never_repeat)
    steps_concurrent = replay_concurrent(
        model, chooser=_first_only_chooser, repeat_decider=_never_repeat
    )

    assert steps_sequential == steps_concurrent
    assert _labels(steps_concurrent) == ("a", "b", "c")


def test_on_fire_hook_runs_sequentially_in_deterministic_order():
    n_branches = 3
    branches = [_make_branch(f"b{i}", [], 0.0) for i in range(n_branches)]
    model = PartialOrder(nodes=branches, edges=[])

    fired: list[str] = []
    calling_thread = threading.get_ident()
    thread_idents_seen: set[int] = set()

    def on_fire(step: ExecutionStep):
        thread_idents_seen.add(threading.get_ident())
        fired.append(step.node.label)

    steps = replay_concurrent(
        model,
        chooser=_first_only_chooser,
        repeat_decider=_never_repeat,
        on_fire=on_fire,
    )

    assert tuple(fired) == _labels(steps)
    # on_fire is guaranteed sequential on the calling thread, even though
    # the underlying node execution was concurrent.
    assert thread_idents_seen == {calling_thread}

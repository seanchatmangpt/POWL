"""Real tests for powl.execution -- the first execution/replay engine in this
repository (confirmed absent before this change: no Marking/enabled/fire
anywhere in the real Python package). No mocks: every test drives real
TaggedPOWL models (built via the repo's own real objects/tagged_powl/
builders.py helpers) through the real replay() engine and asserts on the
real, returned ExecutionStep sequence.
"""

from __future__ import annotations

import pytest

from powl.execution import ExecutionRefusal, ExecutionStep, replay
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.builders import loop, sequence, silent_activity, xor


def _labels(steps: tuple[ExecutionStep, ...]) -> tuple[str | None, ...]:
    return tuple(step.node.label for step in steps)


def _first_only_chooser(node, options):
    return options[0]


def _never_repeat(node, completed):
    return False


def test_sequence_of_activities_fires_in_real_order():
    a = Activity(label="a")
    b = Activity(label="b")
    c = Activity(label="c")
    model = sequence([a, b, c])

    steps = replay(model, chooser=_first_only_chooser, repeat_decider=_never_repeat)

    assert _labels(steps) == ("a", "b", "c")


def test_xor_picks_the_chosen_branch_and_only_that_branch():
    a = Activity(label="a")
    b = Activity(label="b")
    model = xor([a, b])

    def choose_b(node, options):
        for option in options:
            if getattr(option, "label", None) == "b":
                return option
        raise AssertionError("b not offered")

    steps = replay(model, chooser=choose_b, repeat_decider=_never_repeat)

    assert _labels(steps) == ("b",)


def test_chooser_returning_an_unoffered_option_is_refused():
    a = Activity(label="a")
    b = Activity(label="b")
    off_model_activity = Activity(label="not-a-real-option")
    model = xor([a, b])

    def bad_chooser(node, options):
        return off_model_activity

    with pytest.raises(ExecutionRefusal, match="CHOOSER_RETURNED_UNOFFERED_OPTION"):
        replay(model, chooser=bad_chooser, repeat_decider=_never_repeat)


def test_loop_repeats_do_redo_do_when_repeat_decider_says_yes_then_stops():
    do = Activity(label="do")
    redo = Activity(label="redo")
    model = loop(do, redo)

    calls = {"count": 0}

    def allow_one_continuation(node, completed):
        # consulted once per completed start->end traversal; True means
        # "walk the do->redo->do cycle again", False means "stop here".
        calls["count"] += 1
        return completed < 2

    steps = replay(model, chooser=_first_only_chooser, repeat_decider=allow_one_continuation)

    # do, redo, do -- one real continuation past the first do->end decision
    # point, then stopped on the second: two real "do" fires, one "redo" fire.
    assert _labels(steps) == ("do", "redo", "do")
    assert calls["count"] == 2


def test_silent_activity_still_fires_a_real_step_with_none_label():
    tau = silent_activity()
    model = sequence([Activity(label="a"), tau, Activity(label="b")])

    steps = replay(model, chooser=_first_only_chooser, repeat_decider=_never_repeat)

    assert _labels(steps) == ("a", None, "b")


def test_max_steps_budget_is_enforced_as_a_real_refusal():
    do = Activity(label="do")
    redo = Activity(label="redo")
    model = loop(do, redo)

    def always_repeat(node, completed):
        return True

    with pytest.raises(ExecutionRefusal, match="MAX_STEPS_EXCEEDED"):
        replay(model, chooser=_first_only_chooser, repeat_decider=always_repeat, max_steps=5)


def test_activity_min_freq_max_freq_governs_its_own_real_repeat_count():
    # An activity that must fire at least twice, at most three times.
    a = Activity(label="a", min_freq=2, max_freq=3)

    call_log: list[int] = []

    def stop_immediately(node, completed):
        call_log.append(completed)
        return False  # stop as soon as a real choice exists

    steps = replay(a, chooser=_first_only_chooser, repeat_decider=stop_immediately)

    assert _labels(steps) == ("a", "a")
    # consulted once real min_freq (2) is met -- completed == 2 at that point,
    # not 1: two real fires already happened before the choice exists at all.
    assert call_log == [2]


def test_activity_max_freq_hard_caps_without_consulting_repeat_decider_past_it():
    a = Activity(label="a", min_freq=1, max_freq=2)

    def always_say_yes(node, completed):
        return True

    steps = replay(a, chooser=_first_only_chooser, repeat_decider=always_say_yes)

    # real cap at max_freq=2, even though repeat_decider always says "yes"
    assert _labels(steps) == ("a", "a")

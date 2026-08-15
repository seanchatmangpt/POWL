"""Engine test cases derived from the worked example in "Hierarchical
Decomposition of Separable Workflow-Nets" (Kourani, Park, van der Aalst),
Figure 1: a retailer's order-fulfillment process, given in the paper as a
WF-net (Fig. 1a) and its equivalent POWL 2.0 model (Fig. 1b).

We do not re-run the paper's WF-net -> POWL translation algorithm here
(that lives in powl.conversion.to_powl.from_pn); instead we build the
POWL 2.0 model from Fig. 1b directly with this repo's own real
objects/tagged_powl types and drive it through the real replay() engine
(powl.execution), asserting on the real fired ExecutionStep sequence. No
mocks: every model is a real TaggedPOWL structure, every assertion is on
real engine output.
"""

from __future__ import annotations

import pytest

from powl.execution import ExecutionRefusal, ExecutionStep, replay
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.builders import loop, sequence, xor
from powl.objects.tagged_powl.partial_order import PartialOrder


def _labels(steps: tuple[ExecutionStep, ...]) -> tuple[str | None, ...]:
    return tuple(step.node.label for step in steps)


def _never_repeat(node, completed):
    return False


def _build_production_subprocess() -> tuple[PartialOrder, dict[str, Activity]]:
    """The nested partial-order box in Fig. 1b: Gather Production Materials
    and Schedule Production run concurrently; Execute Production depends on
    both; Notify Customer depends only on Schedule Production."""
    gather = Activity(label="Gather Production Materials")
    schedule = Activity(label="Schedule Production")
    execute = Activity(label="Execute Production")
    notify = Activity(label="Notify Customer")

    production = PartialOrder(
        nodes=[gather, schedule, execute, notify],
        edges=[
            (gather, execute),
            (schedule, execute),
            (schedule, notify),
        ],
    )
    return production, {
        "gather": gather,
        "schedule": schedule,
        "execute": execute,
        "notify": notify,
    }


def _index_of(steps: tuple[ExecutionStep, ...], node: Activity) -> int:
    for i, step in enumerate(steps):
        if step.node is node:
            return i
    raise AssertionError(f"{node!r} did not fire")


def test_production_subprocess_respects_the_papers_causal_dependencies():
    production, acts = _build_production_subprocess()

    def chooser(node, options):
        raise AssertionError("the production subprocess has no choice points")

    steps = replay(production, chooser=chooser, repeat_decider=_never_repeat)

    assert set(_labels(steps)) == {
        "Gather Production Materials",
        "Schedule Production",
        "Execute Production",
        "Notify Customer",
    }
    # Real causal constraints from Fig. 1b: gather < execute, schedule <
    # execute, schedule < notify. No constraint between gather and
    # schedule, or between execute and notify -- the model's own real
    # topological_sort() resolves that single-interleaving order, but the
    # dependency-preserving properties below must hold regardless.
    assert _index_of(steps, acts["gather"]) < _index_of(steps, acts["execute"])
    assert _index_of(steps, acts["schedule"]) < _index_of(steps, acts["execute"])
    assert _index_of(steps, acts["schedule"]) < _index_of(steps, acts["notify"])


def test_production_subprocess_interleaving_is_pinned_to_node_insertion_order():
    """The engine does not model true concurrency (see the module docstring
    on POWL/execution/engine.py): for the two nodes with no ordering edge
    between them here -- Gather Production Materials and Schedule
    Production -- PartialOrder.topological_sort() (networkx's Kahn's
    algorithm) breaks the tie by node *insertion order*, not by any other
    rule. _build_production_subprocess() inserts gather before schedule, so
    the real, deterministic fire order pins gather ahead of schedule on
    every replay -- this is an implementation-defined tie-break being
    exercised on purpose, not a causal constraint from Fig. 1b (contrast
    with test_production_subprocess_respects_the_papers_causal_dependencies,
    which only asserts the real causal constraints and deliberately leaves
    gather-vs-schedule order unasserted)."""
    production, acts = _build_production_subprocess()

    def chooser(node, options):
        raise AssertionError("the production subprocess has no choice points")

    steps = replay(production, chooser=chooser, repeat_decider=_never_repeat)

    assert _labels(steps) == (
        "Gather Production Materials",
        "Schedule Production",
        "Execute Production",
        "Notify Customer",
    )
    assert _index_of(steps, acts["gather"]) < _index_of(steps, acts["schedule"])


def test_production_subprocess_is_a_marked_graph_pattern_no_chooser_needed():
    """Definition 3.11 (Marked Graph) / Section 3.4: a partial order is
    structurally equivalent to a sound marked graph -- every flow divergence
    is a parallel split/join, never a decision. Concretely: replaying it
    never needs to consult a chooser at all, because a partial order has no
    real choice points by construction."""
    production, _ = _build_production_subprocess()

    def refusing_chooser(node, options):
        raise AssertionError("REFUSED:UNEXPECTED_CHOICE_POINT_IN_MARKED_GRAPH")

    # Must not raise: no choice point exists to trigger refusing_chooser.
    replay(production, chooser=refusing_chooser, repeat_decider=_never_repeat)


def test_top_level_choice_between_cancel_and_fulfill_paths():
    """Fig. 1b's top-level choice graph: after Place New Order and Check
    Stock Availability, the process either cancels or proceeds to fulfil
    the order (in-stock collection, or the nested production subprocess,
    followed by Ship Order). We model the two-branch decision directly."""
    place_order = Activity(label="Place New Order")
    check_stock = Activity(label="Check Stock Availability")
    cancel = Activity(label="Cancel Order")
    collect = Activity(label="Collect Items from Stock")
    ship = Activity(label="Ship Order")
    production, _ = _build_production_subprocess()

    fulfill_branch = sequence([collect, production, ship])
    decision = xor([cancel, fulfill_branch])
    model = sequence([place_order, check_stock, decision])

    def choose_cancel(node, options):
        for option in options:
            if option is cancel:
                return option
        raise AssertionError("cancel branch not offered")

    steps = replay(model, chooser=choose_cancel, repeat_decider=_never_repeat)

    assert _labels(steps) == (
        "Place New Order",
        "Check Stock Availability",
        "Cancel Order",
    )
    # The fulfillment branch's real activities must never have fired.
    fired_labels = set(_labels(steps))
    assert "Ship Order" not in fired_labels
    assert "Collect Items from Stock" not in fired_labels


def test_top_level_fulfillment_path_runs_production_then_ships():
    place_order = Activity(label="Place New Order")
    check_stock = Activity(label="Check Stock Availability")
    cancel = Activity(label="Cancel Order")
    collect = Activity(label="Collect Items from Stock")
    ship = Activity(label="Ship Order")
    production, acts = _build_production_subprocess()

    fulfill_branch = sequence([collect, production, ship])
    decision = xor([cancel, fulfill_branch])
    model = sequence([place_order, check_stock, decision])

    def choose_fulfill(node, options):
        for option in options:
            if option is fulfill_branch:
                return option
        raise AssertionError("fulfillment branch not offered")

    steps = replay(model, chooser=choose_fulfill, repeat_decider=_never_repeat)

    fired_labels = set(_labels(steps))
    assert "Cancel Order" not in fired_labels
    # Real order: Ship Order fires only after every production activity has.
    ship_index = _index_of(steps, ship)
    for key in ("gather", "schedule", "execute", "notify"):
        assert _index_of(steps, acts[key]) < ship_index
    # And the whole fulfillment path fires strictly after the shared prefix.
    assert _index_of(steps, collect) > _index_of(
        steps, next(s.node for s in steps if s.node.label == "Check Stock Availability")
    )


def test_papers_do_redo_loop_reads_as_repeated_cancellation_then_reorder():
    """The paper notes the top-level control flow includes "the choice
    between ending the process or looping back to the initial state after a
    cancellation." We model that with the repo's real loop() builder
    (POWL's (do (redo do)*) cyclic operator) over a minimal do/redo pair
    standing in for (order-attempt)/(cancel-and-restart)."""
    order_attempt = Activity(label="order-attempt")
    cancel_and_restart = Activity(label="cancel-and-restart")
    model = loop(order_attempt, cancel_and_restart)

    def first_only(node, options):
        return options[0]

    restarts_allowed = {"count": 0}

    def allow_one_restart(node, completed):
        restarts_allowed["count"] += 1
        return completed < 2

    steps = replay(model, chooser=first_only, repeat_decider=allow_one_restart)

    assert _labels(steps) == ("order-attempt", "cancel-and-restart", "order-attempt")
    assert restarts_allowed["count"] == 2


def test_state_machine_choice_graph_refuses_an_option_outside_the_offered_set():
    """Definition 3.10 (State Machine) / Section 3.4: a choice graph is
    structurally equivalent to a sound state machine -- every transition has
    at most one real incoming and one real outgoing place, i.e. exactly one
    path is ever live. The engine enforces this by refusing any chooser
    decision that isn't one of the real, currently-enabled options."""
    in_stock = Activity(label="in-stock-path")
    production = Activity(label="production-path")
    off_model = Activity(label="not-a-real-branch")
    model = xor([in_stock, production])

    def bad_chooser(node, options):
        return off_model

    with pytest.raises(ExecutionRefusal, match="CHOOSER_RETURNED_UNOFFERED_OPTION"):
        replay(model, chooser=bad_chooser, repeat_decider=_never_repeat)

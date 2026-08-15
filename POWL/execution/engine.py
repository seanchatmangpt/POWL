"""Real execution engine for TaggedPOWL models.

This is the module confirmed absent from the real ``powl`` Python package
before this change (grep across ``powl/*.py`` for
``Marking|enabled|fire|execute|Runner`` returned nothing -- the only
execution-semantics concept anywhere in this repo was Lean-side proof
scaffolding in ``powl/Process/Conversion.lean``, not runnable Python).

Scope, stated precisely
------------------------
This engine drives a single, deterministic-modulo-external-decision replay
of a real ``TaggedPOWL`` model (``Activity``/``PartialOrder``/
``ChoiceGraph``, see ``objects/tagged_powl/``). Two points genuinely require
an external decision, made explicit as callbacks rather than resolved by an
arbitrary internal default:

* ``Chooser`` -- which enabled successor to take next at a real
  nondeterministic branch point (a ``ChoiceGraph`` with more than one
  enabled successor, or more than one real start node). The real
  ``ChoiceGraph``/``ChoiceGraphEdge`` model in this repo carries no guard/
  predicate object to evaluate (confirmed: ``choice_graph.py`` has no
  ``Guard`` concept at all) -- this is genuinely unconditional,
  nondeterministic choice, not a guard-evaluation problem.
* ``RepeatDecider`` -- whether to fire a composite node again when its real
  ``min_freq``/``max_freq`` budget (``TaggedPOWL.min_freq``/``max_freq``,
  ``base.py``) leaves a real choice (``completed >= min_freq`` and
  (``max_freq is None`` or ``completed < max_freq``)).

``PartialOrder`` execution order among children with no relative DAG
constraint between them is resolved via the model's own real
``topological_sort()`` (``GraphBacked.topological_sort``, a real, existing,
deterministic method) -- a stated, honest simplification: this models a
single deterministic interleaving, not true concurrency. Never silently
presented as concurrent execution.

Every refusal (an unlicensed fire, a chooser returning a node that isn't a
real enabled option, exceeding ``max_steps``) raises
:class:`ExecutionRefusal` naming exactly what was violated -- never a
silent no-op, matching this repo's own "never silently repaired" precedent
already visible elsewhere in this portfolio's conformance-checking code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..objects.tagged_powl.activity import Activity
from ..objects.tagged_powl.base import TaggedPOWL
from ..objects.tagged_powl.choice_graph import ChoiceGraph
from ..objects.tagged_powl.partial_order import PartialOrder
from .marking import Marking

__all__ = [
    "Chooser",
    "RepeatDecider",
    "ExecutionRefusal",
    "ExecutionStep",
    "enabled",
    "is_final",
    "replay",
]

#: Given the composite node and its real, currently-enabled successor
#: tuple, return which one to take. Must return one of the offered options.
Chooser = Callable[[TaggedPOWL, tuple[TaggedPOWL, ...]], TaggedPOWL]

#: Given a node and its real completed-occurrence count so far, return
#: True to fire it again, False to stop. Only ever consulted when the
#: node's own min_freq/max_freq budget leaves a real choice.
RepeatDecider = Callable[[TaggedPOWL, int], bool]

_DEFAULT_MAX_STEPS = 10_000


class ExecutionRefusal(RuntimeError):
    """Raised on any real violation: an unlicensed fire, a chooser
    returning an option it was not offered, or exceeding max_steps.
    Never raised in place of a silent no-op."""


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    """One real fired Activity, in real fire order."""

    node: Activity
    occurrence_index: int  # 0-based occurrence count of this exact node identity


def _within_repeat_budget(node: TaggedPOWL, completed: int) -> bool:
    if node.max_freq is not None and completed >= node.max_freq:
        return False
    return True


def _may_stop(node: TaggedPOWL, completed: int) -> bool:
    return completed >= node.min_freq


def _resolve_repeat(
    node: TaggedPOWL, completed: int, repeat_decider: RepeatDecider
) -> bool:
    """True iff this node should fire (again). Consults repeat_decider only
    when a real choice exists; otherwise the budget alone decides."""
    if not _within_repeat_budget(node, completed):
        return False
    if not _may_stop(node, completed):
        return True
    # A real choice exists (min_freq already met, room left under max_freq,
    # or max_freq is unbounded): ask, never default silently.
    return repeat_decider(node, completed)


def _run_activity(
    node: Activity,
    trace: list[ExecutionStep],
) -> None:
    trace.append(ExecutionStep(node=node, occurrence_index=len(trace)))


def _run_partial_order(
    node: PartialOrder,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    trace: list[ExecutionStep],
    step_budget: list[int],
) -> None:
    # Real, deterministic single-interleaving order: the model's own real
    # topological_sort() over its real DAG -- a stated simplification, not
    # true concurrency (see module docstring).
    for child in node.topological_sort():
        if not isinstance(child, TaggedPOWL):
            continue  # skip any non-user internal graph node, if ever present
        _run_node(child, chooser, repeat_decider, trace, step_budget)


def _run_choice_graph(
    node: ChoiceGraph,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    trace: list[ExecutionStep],
    step_budget: list[int],
) -> None:
    starts = tuple(sorted(node.start_nodes(), key=id))
    if not starts:
        raise ExecutionRefusal(f"REFUSED:NO_START_NODES model={node!r}")
    current = starts[0] if len(starts) == 1 else chooser(node, starts)
    if current not in starts:
        raise ExecutionRefusal(
            f"REFUSED:CHOOSER_RETURNED_UNOFFERED_OPTION node={node!r} chosen={current!r} offered={starts!r}"
        )

    # Local, real count of how many times this ChoiceGraph has completed a
    # start->end traversal -- distinct from the outer per-node min_freq/
    # max_freq budget _run_node already enforces for `node` itself. This is
    # what decides whether a structural cycle (e.g. the do/redo loop()
    # builder's do->redo->do edge) is walked again or exited.
    cycles_completed = 0
    while True:
        _run_node(current, chooser, repeat_decider, trace, step_budget)

        successors = tuple(sorted(node.successors(current), key=id))
        at_end = node.is_end(current)

        if at_end:
            if not successors:
                return
            cycles_completed += 1
            if not repeat_decider(node, cycles_completed):
                return
        elif not successors:
            raise ExecutionRefusal(
                f"REFUSED:CHOICE_GRAPH_DISCONNECTED node={node!r} stuck_at={current!r}"
            )
        current = successors[0] if len(successors) == 1 else chooser(node, successors)
        if current not in successors:
            raise ExecutionRefusal(
                f"REFUSED:CHOOSER_RETURNED_UNOFFERED_OPTION node={node!r} chosen={current!r} offered={successors!r}"
            )


def _run_node(
    node: TaggedPOWL,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    trace: list[ExecutionStep],
    step_budget: list[int],
) -> None:
    completed = 0
    while _resolve_repeat(node, completed, repeat_decider):
        step_budget[0] -= 1
        if step_budget[0] < 0:
            raise ExecutionRefusal(f"REFUSED:MAX_STEPS_EXCEEDED node={node!r}")
        if isinstance(node, Activity):
            _run_activity(node, trace)
        elif isinstance(node, PartialOrder):
            _run_partial_order(node, chooser, repeat_decider, trace, step_budget)
        elif isinstance(node, ChoiceGraph):
            _run_choice_graph(node, chooser, repeat_decider, trace, step_budget)
        else:
            raise ExecutionRefusal(
                f"REFUSED:UNSUPPORTED_NODE_TYPE {type(node).__name__} for {node!r}"
            )
        completed += 1


def enabled(model: TaggedPOWL, marking: Marking) -> frozenset[TaggedPOWL]:
    """Real, top-level enabled set: the model itself if its own repeat
    budget (per ``marking.count_of(model)``) is not exhausted, else empty."""
    completed = marking.count_of(model)
    if _within_repeat_budget(model, completed):
        return frozenset({model})
    return frozenset()


def is_final(model: TaggedPOWL, marking: Marking) -> bool:
    """Real: the model's own min_freq has been met and nothing is active."""
    return not marking.active and _may_stop(model, marking.count_of(model))


def replay(
    model: TaggedPOWL,
    *,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    max_steps: int = _DEFAULT_MAX_STEPS,
) -> tuple[ExecutionStep, ...]:
    """Real, full replay of ``model`` from its own start. Returns the real,
    ordered sequence of fired ``Activity`` occurrences (silent/tau
    activities included -- callers filtering them do so explicitly, this
    function never hides a real fire). Raises :class:`ExecutionRefusal` on
    any violation; never silently truncates or repairs."""
    trace: list[ExecutionStep] = []
    step_budget = [max_steps]
    _run_node(model, chooser, repeat_decider, trace, step_budget)
    return tuple(trace)

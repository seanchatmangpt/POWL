"""Real, strict prefix-replay conformance checking for TaggedPOWL models.

What this answers
------------------
"Is this real, observed sequence of activity labels a legal (prefix of a)
trace of this real ``TaggedPOWL`` model?" -- decided by literally replaying
the observed sequence through the model's own real structural-walk logic
(the same ``Activity``/``PartialOrder``/``ChoiceGraph`` dispatch and the same
``min_freq``/``max_freq`` repeat semantics :mod:`powl.execution.engine`'s
``_run_node``/``_run_partial_order``/``_run_choice_graph`` already use for
``replay()``), instead of an external ``Chooser``/``RepeatDecider`` callback
picking the next move: here, the next observed label picks it. No new
marking/graph machinery is invented -- this reuses the same
``TaggedPOWL`` structural accessors (``topological_sort()``,
``start_nodes()``/``successors()``/``is_end()``) ``engine.py`` already
walks, and this module's own ``Marking`` import is unused deliberately: at
each replay step, the "real, currently-enabled real activity/activities"
question is answered structurally (by descending into composite nodes) since
``engine.enabled()`` today only ever reports the top-level model itself,
never a leaf-level enabled set -- rederiving that leaf-level view here is
this module's actual job.

Scope, stated precisely -- STRICT PREFIX REPLAY ONLY
------------------------------------------------------
This is a strict prefix-replay conformance check: the observed sequence is
walked in order against the model's own real structure, and the first
observed label with no matching enabled real activity is reported as the
exact point of divergence (by index and label, never just a boolean). This
does **not** attempt alignment-based approximate conformance (inserting or
skipping observed events to find a better-fitting path) the way a full
alpha/ETConformance implementation would -- a real divergence is reported
honestly as a divergence, never silently repaired into a fit. This mirrors
``autofde_lab.powl.conformance``'s own honest scoping of the identical
algorithm over a different (OCEL-driven) model.

One deliberate scoping difference from that OCEL-side checker: this checker
does **not** additionally require the model to reach a real final marking
after the last observed event (that module's ``conforms = final``). A
shorter-than-full, but otherwise perfectly matching, observed sequence is a
valid strict *prefix* of a real trace and is reported as ``fits=True`` --
exhausting the observed sequence mid-replay ends the check, it is not
itself a divergence. Only an actually-present, actually-mismatched label is
a divergence. This is the "strict prefix" in "strict prefix replay": every
event that *is* present must match; nothing is required to be present.

Deterministic tie-break
------------------------
When more than one real enabled node at a decision point (a ``ChoiceGraph``
start set or successor set) could legally produce the next observed label,
the smallest-``id()`` candidate is chosen, using the exact same
``sorted(..., key=id)`` idiom :mod:`powl.execution.engine`'s own
``_run_choice_graph`` already uses to order offered ``Chooser`` options.
This is deterministic within a process (not a semantic/label-based
ranking), and is documented explicitly here -- matching this codebase's own
existing precedent -- rather than left to accidental set-iteration order.

Skippable (``min_freq == 0``) nodes are chased structurally: if the
candidate node's own leading activity can't match but it may legally fire
zero times, this module also considers labels reachable by skipping it
entirely and continuing along the real graph/topological structure (see
``_leading_labels``/``_reachable_through``), so an optional step that the
observed log simply omits is not mistaken for a divergence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..objects.tagged_powl.activity import Activity
from ..objects.tagged_powl.base import TaggedPOWL
from ..objects.tagged_powl.choice_graph import ChoiceGraph
from ..objects.tagged_powl.partial_order import PartialOrder
from .engine import ExecutionRefusal, ExecutionStep, _may_stop, _within_repeat_budget
from .refusals import PowlRefusal

__all__ = ["ConformanceResult", "check_conformance"]


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    """The real, typed verdict -- never a bare boolean."""

    fits: bool
    #: Index into ``observed`` of the first real mismatch, ``None`` if it fits.
    divergence_index: int | None
    #: The observed label that had no matching real enabled activity.
    divergence_label: str | None
    #: The real steps that DID fire before any divergence (the full real
    #: fired sequence, in order, if it fits).
    fired_prefix: tuple[ExecutionStep, ...]


class _Divergence(Exception):
    def __init__(self, index: int, label: str | None) -> None:
        self.index = index
        self.label = label


class _ObservedExhausted(Exception):
    """Internal control-flow signal: the observed sequence ran out while
    the model still had more it could (but is not required to) fire. Not a
    divergence -- see the module docstring's scoping note."""


def _leading_labels(node: TaggedPOWL, _seen: frozenset[int] = frozenset()) -> frozenset[str | None]:
    """All labels that could legally be the very first fired leaf if
    ``node`` began a fresh occurrence right now, considering that a
    ``min_freq == 0`` child may legally fire zero times (in which case the
    leading label comes from whatever the structure visits next)."""
    key = id(node)
    if key in _seen:
        return frozenset()
    seen = _seen | {key}

    if isinstance(node, Activity):
        return frozenset({node.label})

    if isinstance(node, PartialOrder):
        labels: set[str | None] = set()
        for child in node.topological_sort():
            if not isinstance(child, TaggedPOWL):
                continue
            labels |= _leading_labels(child, seen)
            if child.min_freq > 0:
                break
        return frozenset(labels)

    if isinstance(node, ChoiceGraph):
        labels = set()
        for start in sorted(node.start_nodes(), key=id):
            labels |= _reachable_through(node, start, seen)
        return frozenset(labels)

    raise ExecutionRefusal(
        f"REFUSED:UNSUPPORTED_NODE_TYPE {type(node).__name__} for {node!r}",
        refusal=PowlRefusal.UNSUPPORTED_NODE_TYPE,
    )


def _reachable_through(
    graph: ChoiceGraph, current: TaggedPOWL, seen: frozenset[int]
) -> frozenset[str | None]:
    """Labels reachable by entering ``current`` inside ``graph``: either
    from ``current`` itself firing, or -- if ``current`` may legally fire
    zero times -- from whatever ``graph`` visits after skipping it."""
    labels = set(_leading_labels(current, seen))
    if current.min_freq == 0 and not graph.is_end(current):
        for succ in sorted(graph.successors(current), key=id):
            labels |= _reachable_through(graph, succ, seen)
    return labels


def check_conformance(model: TaggedPOWL, observed: Sequence[str | None]) -> ConformanceResult:
    """Real strict prefix-replay of ``observed`` against ``model``'s own
    structure (see module docstring for full scope). Never raises on a log
    that legitimately doesn't fit -- that is reported via the returned
    :class:`ConformanceResult`, not an exception. :class:`ExecutionRefusal`
    is reserved for a genuine structural defect in ``model`` itself (e.g. a
    ``ChoiceGraph`` with no start nodes), exactly as in ``engine.py``."""
    observed = tuple(observed)
    fired: list[ExecutionStep] = []
    pos = [0]

    def fire_activity(node: Activity) -> None:
        if observed[pos[0]] != node.label:
            raise _Divergence(pos[0], observed[pos[0]])
        fired.append(ExecutionStep(node=node, occurrence_index=len(fired)))
        pos[0] += 1

    def pick(candidates: tuple[TaggedPOWL, ...], reach) -> TaggedPOWL | None:
        target = observed[pos[0]]
        for cand in sorted(candidates, key=id):
            if target in reach(cand):
                return cand
        return None

    def run_choice_graph(node: ChoiceGraph) -> None:
        starts = tuple(sorted(node.start_nodes(), key=id))
        if not starts:
            raise ExecutionRefusal(
                f"REFUSED:NO_START_NODES model={node!r}", refusal=PowlRefusal.NO_START_NODES
            )
        current = pick(starts, lambda c: _reachable_through(node, c, frozenset()))
        if current is None:
            raise _Divergence(pos[0], observed[pos[0]])

        cycles_completed = 0
        while True:
            run_node(current)
            if pos[0] >= len(observed):
                raise _ObservedExhausted()

            successors = tuple(sorted(node.successors(current), key=id))
            at_end = node.is_end(current)

            if at_end:
                if not successors:
                    return
                nxt = pick(successors, lambda c: _reachable_through(node, c, frozenset()))
                if nxt is None:
                    # Choosing not to re-enter the cycle is a legal exit,
                    # never a divergence.
                    return
                cycles_completed += 1
                current = nxt
            elif not successors:
                raise ExecutionRefusal(
                    f"REFUSED:CHOICE_GRAPH_DISCONNECTED model={node!r} stuck_at={current!r}",
                    refusal=PowlRefusal.CHOICE_GRAPH_DISCONNECTED,
                )
            else:
                nxt = pick(successors, lambda c: _reachable_through(node, c, frozenset()))
                if nxt is None:
                    raise _Divergence(pos[0], observed[pos[0]])
                current = nxt

    def fire_once(node: TaggedPOWL) -> None:
        if isinstance(node, Activity):
            fire_activity(node)
        elif isinstance(node, PartialOrder):
            for child in node.topological_sort():
                if isinstance(child, TaggedPOWL):
                    run_node(child)
        elif isinstance(node, ChoiceGraph):
            run_choice_graph(node)
        else:
            raise ExecutionRefusal(
                f"REFUSED:UNSUPPORTED_NODE_TYPE {type(node).__name__} for {node!r}",
                refusal=PowlRefusal.UNSUPPORTED_NODE_TYPE,
            )

    def run_node(node: TaggedPOWL) -> None:
        completed = 0
        while True:
            if not _within_repeat_budget(node, completed):
                return
            must_fire = not _may_stop(node, completed)
            if not must_fire:
                if pos[0] >= len(observed) or observed[pos[0]] not in _leading_labels(node):
                    return
            if pos[0] >= len(observed):
                raise _ObservedExhausted()
            fire_once(node)
            completed += 1

    try:
        run_node(model)
        if pos[0] < len(observed):
            raise _Divergence(pos[0], observed[pos[0]])
    except _Divergence as diverged:
        return ConformanceResult(
            fits=False,
            divergence_index=diverged.index,
            divergence_label=diverged.label,
            fired_prefix=tuple(fired),
        )
    except _ObservedExhausted:
        pass

    return ConformanceResult(
        fits=True,
        divergence_index=None,
        divergence_label=None,
        fired_prefix=tuple(fired),
    )

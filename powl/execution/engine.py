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

Concretely: ``topological_sort()`` delegates to ``networkx.topological_sort``
(Kahn's algorithm) over the node's internal ``DiGraph``. For two nodes with
no ordering edge between them, the tie is broken by *node insertion order*
into that graph (the order ``add_nodes`` was called, i.e. the order given to
``PartialOrder(nodes=...)``/``add_edge``) -- not by label, not randomly, and
not re-decided per replay call. This makes a given ``PartialOrder`` instance
deterministic across repeated ``replay()`` calls, but the specific
interleaving picked among unordered siblings is an implementation detail of
node-construction order, not a semantic guarantee -- callers must not depend
on which of several DAG-equivalent orderings comes out, only on the real
causal constraints the ``PartialOrder``'s edges actually encode.

Concurrency
-----------
``replay()`` remains the default, fully single-threaded reference semantics
described above -- it never spawns threads or async tasks, for exactly the
reason given above (no shared-state race is possible because nothing runs
off the calling thread).

``replay_concurrent()`` is a real, opt-in second mode for genuinely
independent ``PartialOrder`` siblings. It identifies each real topological
*generation* of a ``PartialOrder`` (via ``networkx.topological_generations``
over the node's own ``.graph`` -- one generation is exactly the set of
nodes with no path between any two of them, i.e. real siblings with no
relative DAG ordering constraint). A generation of exactly one node runs on
the calling thread directly, identical to ``replay()``, with no thread pool
overhead. A generation of more than one node fires every member inside a
``ThreadPoolExecutor``: each worker recurses into the same ``_run_node``
logic used by ``replay()``, but with its OWN private, per-worker trace list
and step-budget snapshot -- no shared mutable state (no shared list, no
shared counter, no lock) is ever touched from a worker thread. Once every
worker in the round has completed (or raised), the calling thread merges
each worker's private sub-trace into the shared trace, in deterministic
generation-then-node-index order (never thread-completion order), invokes
``on_fire`` once per real fired step in that same order, advances the
shared step budget by the real total steps consumed, and only then raises
the first error from that round, again in that same deterministic order if
any worker raised. This is the "no shared mutable state touched from a
worker thread at all" discipline: simpler to reason about than a lock,
and it is what makes the merged trace reproducible in content even though
the underlying per-branch work happened concurrently.

Every refusal (an unlicensed fire, a chooser returning a node that isn't a
real enabled option, exceeding ``max_steps``) raises
:class:`ExecutionRefusal` naming exactly what was violated -- never a
silent no-op, matching this repo's own "never silently repaired" precedent
already visible elsewhere in this portfolio's conformance-checking code.
This holds identically for both ``replay()`` and ``replay_concurrent()``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx

from ..objects.tagged_powl.activity import Activity
from ..objects.tagged_powl.base import TaggedPOWL
from ..objects.tagged_powl.choice_graph import ChoiceGraph
from ..objects.tagged_powl.partial_order import PartialOrder
from .marking import Marking
from .refusals import PowlRefusal

__all__ = [
    "Chooser",
    "RepeatDecider",
    "ExecutionRefusal",
    "ExecutionStep",
    "enabled",
    "is_final",
    "replay",
    "replay_concurrent",
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

    def __init__(self, message: str, *, refusal: PowlRefusal | None = None) -> None:
        super().__init__(message)
        self.refusal: PowlRefusal | None = refusal


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
    run_node_fn: Callable[
        [TaggedPOWL, Chooser, RepeatDecider, list[ExecutionStep], list[int]], None
    ]
    | None = None,
) -> None:
    """Shared between :func:`replay` and :func:`replay_concurrent` -- a
    ``ChoiceGraph`` has no internal concurrency of its own (a real, single
    active path is walked start->end), so this body is identical for both
    entry points. ``run_node_fn`` is how each entry point recurses into its
    own node-dispatch (sequential ``_run_node`` for ``replay``, the
    concurrency-aware ``_run_node_concurrent`` for ``replay_concurrent``),
    so nested ``PartialOrder``s reachable from inside a ``ChoiceGraph`` still
    get real concurrent treatment under ``replay_concurrent``."""
    if run_node_fn is None:
        run_node_fn = _run_node
    starts = tuple(sorted(node.start_nodes(), key=id))
    if not starts:
        raise ExecutionRefusal(
            f"REFUSED:NO_START_NODES model={node!r}", refusal=PowlRefusal.NO_START_NODES
        )
    current = starts[0] if len(starts) == 1 else chooser(node, starts)
    if current not in starts:
        raise ExecutionRefusal(
            f"REFUSED:CHOOSER_RETURNED_UNOFFERED_OPTION node={node!r} chosen={current!r} offered={starts!r}",
            refusal=PowlRefusal.CHOOSER_RETURNED_UNOFFERED_OPTION,
        )

    # Local, real count of how many times this ChoiceGraph has completed a
    # start->end traversal -- distinct from the outer per-node min_freq/
    # max_freq budget _run_node already enforces for `node` itself. This is
    # what decides whether a structural cycle (e.g. the do/redo loop()
    # builder's do->redo->do edge) is walked again or exited.
    cycles_completed = 0
    while True:
        run_node_fn(current, chooser, repeat_decider, trace, step_budget)

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
                f"REFUSED:CHOICE_GRAPH_DISCONNECTED node={node!r} stuck_at={current!r}",
                refusal=PowlRefusal.CHOICE_GRAPH_DISCONNECTED,
            )
        current = successors[0] if len(successors) == 1 else chooser(node, successors)
        if current not in successors:
            raise ExecutionRefusal(
                f"REFUSED:CHOOSER_RETURNED_UNOFFERED_OPTION node={node!r} chosen={current!r} offered={successors!r}",
                refusal=PowlRefusal.CHOOSER_RETURNED_UNOFFERED_OPTION,
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
            raise ExecutionRefusal(
                f"REFUSED:MAX_STEPS_EXCEEDED node={node!r}", refusal=PowlRefusal.MAX_STEPS_EXCEEDED
            )
        if isinstance(node, Activity):
            _run_activity(node, trace)
        elif isinstance(node, PartialOrder):
            _run_partial_order(node, chooser, repeat_decider, trace, step_budget)
        elif isinstance(node, ChoiceGraph):
            _run_choice_graph(node, chooser, repeat_decider, trace, step_budget, run_node_fn=_run_node)
        else:
            raise ExecutionRefusal(
                f"REFUSED:UNSUPPORTED_NODE_TYPE {type(node).__name__} for {node!r}",
                refusal=PowlRefusal.UNSUPPORTED_NODE_TYPE,
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


def _run_partial_order_concurrent(
    node: PartialOrder,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    trace: list[ExecutionStep],
    step_budget: list[int],
    max_workers: int | None,
) -> None:
    """Real generation-based concurrent replacement for
    :func:`_run_partial_order`'s plain ``topological_sort()`` loop.

    ``nx.topological_generations`` gives exactly the real topological
    generations of the node's own DAG: one generation is the set of nodes
    with no path between any two of them, i.e. real siblings with no
    relative DAG ordering constraint -- filtered here to real ``TaggedPOWL``
    nodes only, same filtering ``_run_partial_order`` already applies.

    A generation of exactly one node runs on the calling thread directly
    (no thread-pool overhead, identical to the sequential engine). A
    generation of more than one node fires every member inside a
    ``ThreadPoolExecutor``: each worker gets its OWN private trace list and
    its OWN private step-budget snapshot -- no shared mutable state is ever
    touched from a worker thread. Once the whole round completes, the
    calling thread merges each worker's private sub-trace into ``trace``,
    and advances the real shared ``step_budget``, in deterministic
    generation-then-node-index order (never thread-completion order); any
    worker's :class:`ExecutionRefusal` is re-raised afterward, picking the
    first one in that same deterministic order.
    """
    generations = [
        [child for child in gen if isinstance(child, TaggedPOWL)]
        for gen in nx.topological_generations(node.graph)
    ]

    for generation in generations:
        if not generation:
            continue  # a real empty generation (no user nodes) is a no-op

        if len(generation) == 1:
            _run_node_concurrent(
                generation[0], chooser, repeat_decider, trace, step_budget, max_workers
            )
            continue

        # A genuine multi-member ready set: real concurrent firing.
        budget_at_round_start = step_budget[0]
        workers = max_workers if max_workers is not None else len(generation)
        workers = max(1, workers)  # guard (e): never construct a 0-worker pool

        results: list[tuple[list[ExecutionStep], int] | None] = [None] * len(generation)
        errors: list[ExecutionRefusal | None] = [None] * len(generation)

        def _worker(idx: int, child: TaggedPOWL) -> None:
            local_trace: list[ExecutionStep] = []
            # Each worker gets its own private budget snapshot, seeded from
            # the real shared value at round start -- never the shared list
            # itself, so no worker thread ever mutates shared state.
            local_budget = [budget_at_round_start]
            try:
                _run_node_concurrent(
                    child, chooser, repeat_decider, local_trace, local_budget, max_workers
                )
            except ExecutionRefusal as exc:
                errors[idx] = exc
                return
            consumed = budget_at_round_start - local_budget[0]
            results[idx] = (local_trace, consumed)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, idx, child) for idx, child in enumerate(generation)]
            for future in futures:
                future.result()  # surface any non-ExecutionRefusal exception immediately

        # Merge/raise sequentially on the calling thread, in real
        # deterministic generation-then-node-index order -- never
        # thread-completion order.
        for idx in range(len(generation)):
            if errors[idx] is not None:
                raise errors[idx]

        for idx in range(len(generation)):
            local_trace, consumed = results[idx]  # type: ignore[misc]
            trace.extend(local_trace)
            step_budget[0] -= consumed


def _run_node_concurrent(
    node: TaggedPOWL,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    trace: list[ExecutionStep],
    step_budget: list[int],
    max_workers: int | None,
) -> None:
    """Concurrency-aware mirror of :func:`_run_node`. ``Activity`` and
    ``ChoiceGraph`` handling is byte-for-byte identical to :func:`_run_node`
    (no internal concurrency is possible for either); only the
    ``PartialOrder`` branch differs, delegating to
    :func:`_run_partial_order_concurrent` instead of the plain sequential
    :func:`_run_partial_order`."""
    completed = 0
    while _resolve_repeat(node, completed, repeat_decider):
        step_budget[0] -= 1
        if step_budget[0] < 0:
            raise ExecutionRefusal(
                f"REFUSED:MAX_STEPS_EXCEEDED node={node!r}", refusal=PowlRefusal.MAX_STEPS_EXCEEDED
            )
        if isinstance(node, Activity):
            _run_activity(node, trace)
        elif isinstance(node, PartialOrder):
            _run_partial_order_concurrent(
                node, chooser, repeat_decider, trace, step_budget, max_workers
            )
        elif isinstance(node, ChoiceGraph):
            _run_choice_graph(
                node,
                chooser,
                repeat_decider,
                trace,
                step_budget,
                run_node_fn=lambda n, c, r, t, b: _run_node_concurrent(
                    n, c, r, t, b, max_workers
                ),
            )
        else:
            raise ExecutionRefusal(
                f"REFUSED:UNSUPPORTED_NODE_TYPE {type(node).__name__} for {node!r}",
                refusal=PowlRefusal.UNSUPPORTED_NODE_TYPE,
            )
        completed += 1


def replay_concurrent(
    model: TaggedPOWL,
    *,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    on_fire: Callable[[ExecutionStep], Any] | None = None,
    max_steps: int = _DEFAULT_MAX_STEPS,
    max_workers: int | None = None,
) -> tuple[ExecutionStep, ...]:
    """Real, opt-in concurrent replay of ``model``. Identical chooser/
    repeat_decider consultation and identical :class:`ExecutionRefusal`
    semantics to :func:`replay` for every case ``replay`` already raises.
    The only real behavioral difference: within a ``PartialOrder``, a real
    topological generation of more than one ready sibling is fired inside a
    ``ThreadPoolExecutor`` instead of one at a time (see the module
    docstring's Concurrency section and :func:`_run_partial_order_concurrent`
    for the full synchronization discipline).

    ``on_fire``, if given, is invoked once per real fired
    :class:`ExecutionStep`, sequentially on the calling thread, in the same
    deterministic order as the returned tuple -- after the entire replay has
    completed, never from a worker thread and never in thread-completion
    order.
    """
    trace: list[ExecutionStep] = []
    step_budget = [max_steps]
    _run_node_concurrent(model, chooser, repeat_decider, trace, step_budget, max_workers)
    result = tuple(trace)
    if on_fire is not None:
        for step in result:
            on_fire(step)
    return result

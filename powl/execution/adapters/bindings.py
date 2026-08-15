"""Real, thin adapter layering caller-supplied action bindings and evidence
recording on top of :func:`powl.execution.engine.replay_concurrent`.

Honesty about what this reuses vs. what it adds
------------------------------------------------
This module does NOT reimplement or fork any firing/concurrency logic. It
reuses ``replay_concurrent`` as-is, driving it with a real ``on_fire``
callback, and lets the engine's own ``_run_node_concurrent`` /
``_run_partial_order_concurrent`` machinery do all real structural firing
and node-level concurrency exactly as documented in ``engine.py``.
``engine.py`` remains the only place in this whole package that constructs
a ``ThreadPoolExecutor`` for *node-level* (structural POWL-firing)
concurrency.

This module adds a SECOND, independent ``ThreadPoolExecutor`` -- scoped
ONLY to invoking caller-supplied ``action_bindings`` callables, never to
firing POWL structure. Naming both pools and why they are separate:

* ``engine.py``'s pool fires POWL structure -- it decides *which* node fires
  *when*, based on real DAG generations inside a ``PartialOrder``.
* this module's pool invokes caller side effects -- once the engine has
  already decided a node fired, this pool calls whatever real callable the
  caller registered for that node's label.

Be precise about isolation, not merely asserted
-------------------------------------------------
Read literally, per the real, current ``replay_concurrent`` signature in
``engine.py``: ``on_fire: Callable[[ExecutionStep], Any] | None`` is invoked
**once per fired step, sequentially, on the calling thread, only AFTER the
entire replay has already completed** -- not from a worker thread, and not
per structural "round" (``replay_concurrent``'s own docstring: "after the
entire replay has completed"; verified in this module's own read of
``engine.py`` before writing this file). There is no live per-round
boundary exposed to ``on_fire`` at all -- by the time ``on_fire`` is called
even once, EVERY worker thread engine.py's own ``ThreadPoolExecutor`` ever
created has already finished and been torn down (each ``with
ThreadPoolExecutor(...)`` block in ``_run_partial_order_concurrent`` exits,
joining its workers, before ``_run_node_concurrent`` returns up to
``replay_concurrent``, which only then starts calling ``on_fire``).

Consequently: **a slow binding can never block "the next round's
structural firing," because by the time any binding runs, there is no
"next round" of structural firing left to block -- structural firing and
binding invocation are two entirely sequential phases of one
``replay_with_bindings`` call, not two pools running concurrently with
each other.** This module does not claim the two pools give live
pipeline-style overlap between structural firing and binding invocation;
that isolation was never built, and asserting it would overclaim. What IS
real: this module's own binding-invocation pool still fires all matched
bindings for the whole replay CONCURRENTLY with each other (not one at a
time), exactly mirroring engine.py's own (a)-(e) discipline for a single
batch -- invoke concurrently, collect results/errors per-index, then
report/record sequentially in deterministic order, re-raising the first
error (in that same deterministic order) only after recording every step.

Because the engine's real ``on_fire`` hook has no round concept, "the
round" this module records/raises over is the entire replay's fired-step
sequence for one ``replay_with_bindings`` call -- the only granularity the
real API actually offers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Mapping

from ...objects.tagged_powl.base import TaggedPOWL
from ..engine import (
    Chooser,
    ExecutionStep,
    RepeatDecider,
    _DEFAULT_MAX_STEPS,
    replay_concurrent,
)
from .evidence import EvidenceRecorder

__all__ = ["replay_with_bindings"]


def replay_with_bindings(
    model: TaggedPOWL,
    *,
    chooser: Chooser,
    repeat_decider: RepeatDecider,
    action_bindings: Mapping[str, Callable[[TaggedPOWL], Any]] | None = None,
    recorder: EvidenceRecorder | None = None,
    max_steps: int = _DEFAULT_MAX_STEPS,
    max_workers: int | None = None,
) -> tuple[ExecutionStep, ...]:
    """Real replay of ``model`` via :func:`replay_concurrent`, invoking any
    matching ``action_bindings`` callable for each real fired step and
    recording every real fired step's outcome via ``recorder``.

    Steps, matching the real (a)-(e) discipline named in this module's own
    docstring:

    (a) Drive ``replay_concurrent`` with a real ``on_fire`` callback that
        merely accumulates the real, already-fired, already-ordered steps
        (no binding is invoked from inside ``on_fire`` itself -- ``on_fire``
        runs on the calling thread only after the whole structural replay
        has completed, per the real signature read from ``engine.py``).
    (b) Once ``replay_concurrent`` returns, look up
        ``action_bindings.get(step.node.label)`` for every accumulated step
        and invoke every match CONCURRENTLY in a real
        ``ThreadPoolExecutor`` sized to the number of matched steps (or
        ``max_workers`` if given) -- results and exceptions collected per
        index, never reported from the worker thread itself.
    (c) Call ``recorder.record(...)`` sequentially, once for EVERY real
        fired step (bound or not, success or error), in real deterministic
        fire order, if a ``recorder`` was supplied.
    (d) If any binding raised, re-raise the FIRST one (in that same
        deterministic fire order) -- but only AFTER step (c) has finished
        recording every step. A binding's exception is re-raised as-is
        (not wrapped) -- callers see the real exception the binding itself
        raised.

    Unbound labels (no entry in ``action_bindings``, or ``action_bindings``
    is ``None``/empty) are still real fired steps: they get no callable
    invocation, but ``recorder.record`` still sees them, with an
    ``{"status": "unbound"}`` outcome, so an evidence trail is complete
    over every real fired step, not only the bound ones.
    """
    fired: list[ExecutionStep] = []

    def _on_fire(step: ExecutionStep) -> None:
        # (a) Pure accumulation. No binding invocation here: on_fire, per
        # the real engine.py contract, only ever runs sequentially on the
        # calling thread, after the entire structural replay is done -- so
        # there is nothing to gain, and real ordering discipline to lose,
        # by invoking bindings mid-callback instead of after the fact.
        fired.append(step)

    replay_concurrent(
        model,
        chooser=chooser,
        repeat_decider=repeat_decider,
        on_fire=_on_fire,
        max_steps=max_steps,
        max_workers=max_workers,
    )

    bindings = action_bindings or {}
    bound_indices = [
        idx for idx, step in enumerate(fired) if step.node.label in bindings
    ]

    results: list[Any] = [None] * len(fired)
    errors: list[BaseException | None] = [None] * len(fired)

    if bound_indices:
        # (b) Real concurrent invocation of every matched binding.
        pool_size = max_workers if max_workers is not None else len(bound_indices)
        pool_size = max(1, pool_size)  # never construct a 0-worker pool

        def _invoke(idx: int) -> None:
            step = fired[idx]
            binding = bindings[step.node.label]
            try:
                results[idx] = binding(step.node)
            except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
                # real exception a caller's binding raises must be captured
                # here (never lost to a worker thread) and re-raised later,
                # in step (d), from the calling thread instead.
                errors[idx] = exc

        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            futures = [pool.submit(_invoke, idx) for idx in bound_indices]
            for future in futures:
                future.result()  # surface any non-captured exception immediately

    # (c) Sequential recording, in real deterministic fire order, for
    # EVERY real fired step -- bound or not.
    bound_index_set = set(bound_indices)
    first_error: BaseException | None = None
    for idx, step in enumerate(fired):
        if idx not in bound_index_set:
            outcome: Mapping[str, Any] = {"status": "unbound"}
        elif errors[idx] is not None:
            outcome = {"status": "error", "error": errors[idx]}
            if first_error is None:
                first_error = errors[idx]
        else:
            outcome = {"status": "success", "result": results[idx]}
        if recorder is not None:
            recorder.record(step.node.label, step.node, outcome)

    # (d) Re-raise the first error, in deterministic fire order, only AFTER
    # every step has been recorded.
    if first_error is not None:
        raise first_error

    return tuple(fired)

# Fortune-5 Concurrent POWL Runner — Design

## Context

`~/POWL/execution/engine.py` replays a `TaggedPOWL` model as a single
deterministic interleaving (`topological_sort()`, one activity at a time).
Two other repos in this portfolio each independently built a more capable
executor around a *different* object model (`PowlNode`/`Atom` in
`algebra.py`, not `TaggedPOWL`):

- `~/autofde-lab/src/autofde_lab/powl/` — `runner.py` fires an entire
  round's enabled set concurrently via a real, correctly-locked
  `ThreadPoolExecutor`; `guard_executor.py` adds deterministic guard
  evaluation, frequency-aware repetition, checkpoint/resume, and typed
  refusals (`PowlRefusal` enum); `conformance.py` replays an observed
  activity sequence against the real model to report the exact point of
  divergence.
- `~/gymact/src/gymact/powl/` — a diverged fork of the same subpackage
  (same filenames, same copyright header, same design laws), with its own
  extras (`_canonical.py`, `_turtle.py`, `spec.py`) autofde-lab lacks.

Goal: make `~/POWL` the single canonical engine so gym agents (starting
with `~/gymact`) stop reimplementing a workflow runner. Per user decision,
this port takes autofde-lab's `powl/` as the sole source (gymact's
independent fork is left as-is for now, not diffed in this pass), and
targets `~/POWL`'s existing `TaggedPOWL`/`Activity`/`PartialOrder`/
`ChoiceGraph` object model — not a second, parallel `PowlNode` type.

This is deliberately scoped as two phases so the core engine stays
dependency-free (no OCEL, no gym-specific action-binding types) and is
genuinely reusable by a customer who has neither.

## Phase 1 — Concurrency-safe core (in scope now)

Ported/adapted onto `TaggedPOWL`, added to `~/POWL/execution/`:

1. **`replay_concurrent()`** — new function alongside the existing
   `replay()` in `engine.py`. Fires every node enabled in a round via a
   real `ThreadPoolExecutor(max_workers=len(round))`, following
   autofde-lab's proven sequence: (a) advance state for the whole batch
   sequentially on the calling thread first (state mutation is cheap/pure,
   keeps a consistent view before anything concurrent runs), (b) invoke
   per-node work concurrently only for side-effect-free/caller-supplied
   callbacks, (c) record/report sequentially in deterministic batch order,
   (d) raise the first error in that same deterministic order — never let
   thread completion order leak into observable behavior. Reuses the
   existing `ExecutionRefusal` discipline; a `0`-sized round is a real
   no-op, not a `ValueError` crash (the exact bug autofde-lab's own code
   comments document fixing).
2. **Typed refusal vocabulary** — a `PowlRefusal` `StrEnum` in
   `execution/refusals.py`, covering the generic subset applicable to
   `TaggedPOWL` (`CHOICE_GRAPH_DISCONNECTED`, `CHOOSER_RETURNED_UNOFFERED_OPTION`,
   `MAX_STEPS_EXCEEDED`/`TRANSITION_BUDGET_EXHAUSTED`, `BOUND_EXHAUSTED`,
   `NO_GUARD_MATCHED`). `ExecutionRefusal` gains an optional `.refusal:
   PowlRefusal` attribute; existing string-matching tests keep working
   unchanged (message format unchanged), new code can match on the enum.
3. **Conformance checking** — `execution/conformance.py`:
   `check_conformance(model, observed: Sequence[str | None]) ->
   ConformanceResult`, replaying an observed label sequence through the
   model's own real `enabled()`/`replay()` machinery and reporting the
   exact index/label of the first divergence. Deliberately generic over
   *any* iterable of observed labels — no OCEL dependency. (OCEL becomes
   just one possible source of that sequence, wired in Phase 2.)
4. **gymact integration** — `~/gymact/src/gymact/powl/executor.py`'s
   `Marking`/`enabled`/replay logic is replaced with an import of
   `powl.execution` (the now-canonical package). gymact's unique extras
   (`_canonical.py`, `_turtle.py`, `spec.py`) are untouched. gymact's own
   `PowlNode`-based `algebra.py`/`guard_executor.py` stay as gymact's
   concern unless/until a later pass migrates gymact's own model onto
   `TaggedPOWL` too — out of scope here; this pass only removes gymact's
   duplicate *executor* (the piece the original ask named).

## Phase 2 — Evidence + action-binding adapters (in scope now, layered)

Added as an **optional** module, not a required dependency of Phase 1:

5. **`execution/adapters/bindings.py`** — `run_with_bindings(model, *,
   action_bindings: Mapping[str, Callable], ...)`, layering
   autofde-lab's action-binding-per-fired-node pattern on top of
   `replay_concurrent()`, via the same "fire sequentially, bind
   concurrently, record sequentially, raise first error in order"
   discipline.
6. **`execution/adapters/evidence.py`** — a minimal, dependency-free
   `EvidenceRecorder` protocol (one method: `record(activity: str,
   objects, outcome: Mapping)`) that a caller can satisfy with a real OCEL
   recorder (autofde-lab/gymact already have one) or anything else. Core
   engine never imports OCEL; this adapter is the only place a
   caller-supplied recorder is invoked, and only when supplied.

## Testing (Chicago style, no mocks)

- Real `TaggedPOWL` models (reusing `builders.py`/the paper-derived
  fixtures already in `tests/test_execution_paper_examples.py`), real
  `replay_concurrent()` calls, real `ThreadPoolExecutor` — no
  `unittest.mock`/`Mock`/`patch`.
- A concurrency test that genuinely exercises >1 worker (e.g. a
  `PartialOrder` with ≥2 independent branches) and asserts on the real,
  deterministic *recorded* order despite concurrent firing — proving the
  "recorded in batch order regardless of thread completion order" law
  with real threads, not a mocked executor.
- Conformance tests replay real observed sequences (a conforming one, one
  with a real injected divergence) against real models and assert on the
  real reported divergence index/label.
- `grep -rn "unittest.mock\|Mock(\|MagicMock\|patch(\|monkeypatch"` over
  `tests/` after every change, target: zero matches.

## Non-goals (this pass)

- Reconciling gymact's independently-diverged fork's unique logic back
  into `~/POWL` (explicitly deferred per user decision).
- Migrating gymact's own `PowlNode`/`algebra.py` model onto `TaggedPOWL`.
- `autofde-lab`'s SREGym-specific bindings, `soundness_bridge.py`,
  `membership.py`, `mutations.py`, `claudecode_reference_model.py` —
  domain-specific, not part of a generic engine.

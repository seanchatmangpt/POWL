from __future__ import annotations

import asyncio
from contextvars import ContextVar
import hashlib
import inspect
import json
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.base import TaggedPOWL
from powl.objects.tagged_powl.choice_graph import ChoiceGraph
from powl.objects.tagged_powl.partial_order import PartialOrder

from .contracts import (
    ActuationReceipt,
    ActivityCommand,
    BindState,
    ChoiceCandidate,
    ChoiceDecision,
    ClaimState,
    RefusalCode,
    RepetitionDecision,
    RunBinding,
    RunReceipt,
    RunnerConfig,
    SelectionPolicy,
    SelectionRefused,
    Standing,
    StepKind,
    StepReceipt,
    StrictSelectionPolicy,
)
from .store import InMemoryRunStore, RunStore


@dataclass(frozen=True)
class _RunContext:
    run_id: str
    workflow_id: str
    model_digest: str
    variables: Mapping[str, Any]
    cancel_event: Optional[asyncio.Event]
    owner: str


@dataclass
class _ModelResult:
    standing: Standing
    output: Any = None
    reason: Optional[str] = None


class _AdmissionError(Exception):
    def __init__(self, standing: Standing, code: RefusalCode, detail: str) -> None:
        super().__init__(detail)
        self.standing = standing
        self.code = code
        self.detail = detail


class WorkflowRunner:
    """Receipted asynchronous executor for the core TaggedPOWL language."""

    def __init__(
        self,
        actuator: Any,
        *,
        store: Optional[RunStore] = None,
        selection_policy: Optional[SelectionPolicy] = None,
        config: Optional[RunnerConfig] = None,
    ) -> None:
        self._actuator = actuator
        self._store = store or InMemoryRunStore()
        self._selection = selection_policy or StrictSelectionPolicy()
        self._config = config or RunnerConfig()
        if self._config.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self._config.retry.max_attempts < 1:
            raise ValueError("retry.max_attempts must be >= 1")
        self._semaphore = asyncio.Semaphore(self._config.max_concurrency)
        self._context: ContextVar[_RunContext] = ContextVar("powl_runtime_context")

    async def run(
        self,
        model: TaggedPOWL,
        *,
        run_id: str,
        workflow_id: str,
        variables: Optional[Mapping[str, Any]] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> RunReceipt:
        started = time.time()
        if not run_id or not workflow_id:
            return self._terminal_run(
                run_id=run_id,
                workflow_id=workflow_id,
                model_digest="",
                standing=Standing.REFUSED,
                started=started,
                reason="ADMISSION: run_id and workflow_id are required",
            )

        try:
            snapshot = self._snapshot(model)
            self._admit(snapshot)
            model_digest = self._model_digest_for(snapshot)
        except _AdmissionError as exc:
            return self._terminal_run(
                run_id=run_id,
                workflow_id=workflow_id,
                model_digest="",
                standing=exc.standing,
                started=started,
                reason="%s: %s" % (exc.code.value, exc.detail),
            )
        except Exception as exc:
            return self._terminal_run(
                run_id=run_id,
                workflow_id=workflow_id,
                model_digest="",
                standing=Standing.REFUSED,
                started=started,
                reason="ADMISSION: %s" % exc,
            )

        binding = RunBinding(run_id=run_id, workflow_id=workflow_id, model_digest=model_digest)
        bind = await self._store.bind_run(binding)
        if bind.state == BindState.CONFLICT:
            return self._terminal_run(
                run_id=run_id,
                workflow_id=workflow_id,
                model_digest=model_digest,
                standing=Standing.REFUSED,
                started=started,
                reason="%s: run_id is already bound to a different admitted subject" % RefusalCode.RUN_ID_REUSE.value,
            )
        if bind.receipt is not None:
            return replace(bind.receipt, replayed=True)

        context = _RunContext(
            run_id=run_id,
            workflow_id=workflow_id,
            model_digest=model_digest,
            variables=dict(variables or {}),
            cancel_event=cancel_event,
            owner="runner-%s" % uuid.uuid4().hex,
        )
        token = self._context.set(context)
        try:
            result = await self._execute_model(snapshot, "root", {})
            steps = await self._store.list_steps(run_id)
            receipt = RunReceipt(
                run_id=run_id,
                workflow_id=workflow_id,
                model_digest=model_digest,
                standing=result.standing,
                started_at=started,
                finished_at=time.time(),
                receipt_digest=self._receipt_digest(steps),
                steps=tuple(steps),
                reason=result.reason,
                replayed=False,
            )
            await self._store.save_run(receipt)
            return receipt
        finally:
            self._context.reset(token)

    def _terminal_run(
        self,
        *,
        run_id: str,
        workflow_id: str,
        model_digest: str,
        standing: Standing,
        started: float,
        reason: str,
    ) -> RunReceipt:
        return RunReceipt(
            run_id=run_id,
            workflow_id=workflow_id,
            model_digest=model_digest,
            standing=standing,
            started_at=started,
            finished_at=time.time(),
            receipt_digest=self._sha256_text(reason),
            steps=(),
            reason=reason,
        )

    def _snapshot(self, model: TaggedPOWL) -> TaggedPOWL:
        if isinstance(model, Activity):
            return model.clone(deep=True)
        if isinstance(model, PartialOrder):
            mapping = {node: self._snapshot(node) for node in model.children}
            snap = PartialOrder(
                nodes=[mapping[node] for node in model.children],
                edges=[(mapping[u], mapping[v]) for u, v in model.get_edges()],
                min_freq=model.min_freq,
                max_freq=model.max_freq,
            )
            snap.attributes = dict(model.attributes)
            return snap
        if isinstance(model, ChoiceGraph):
            mapping = {node: self._snapshot(node) for node in model.children}
            snap = ChoiceGraph(
                nodes=[mapping[node] for node in model.children],
                edges=[(mapping[u], mapping[v]) for u, v in model.get_edges()],
                start_nodes=[mapping[node] for node in model.start_nodes()],
                end_nodes=[mapping[node] for node in model.end_nodes()],
                min_freq=model.min_freq,
                max_freq=model.max_freq,
            )
            snap.attributes = dict(model.attributes)
            return snap
        raise _AdmissionError(
            Standing.UNSUPPORTED,
            RefusalCode.UNSUPPORTED_MODEL,
            "unsupported TaggedPOWL subtype %s" % type(model).__name__,
        )

    def _admit(self, model: TaggedPOWL) -> None:
        count = self._admit_recursive(model, "root")
        if count > self._config.max_model_nodes:
            raise _AdmissionError(
                Standing.REFUSED,
                RefusalCode.BOUND_EXCEEDED,
                "model contains %d nodes; max_model_nodes=%d" % (count, self._config.max_model_nodes),
            )

    def _admit_recursive(self, model: TaggedPOWL, path: str) -> int:
        try:
            json.dumps(model.attributes, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise _AdmissionError(
                Standing.REFUSED,
                RefusalCode.ADMISSION,
                "%s attributes must be JSON-compatible: %s" % (path, exc),
            )
        if isinstance(model, Activity):
            return 1
        if isinstance(model, PartialOrder):
            model.validate()
        elif isinstance(model, ChoiceGraph):
            model.validate_connectivity()
        else:
            raise _AdmissionError(
                Standing.UNSUPPORTED,
                RefusalCode.UNSUPPORTED_MODEL,
                "%s has unsupported model type %s" % (path, type(model).__name__),
            )

        refs = self._child_refs(model, path)
        total = 1
        for child in model.children:
            total += self._admit_recursive(child, "%s/%s" % (path, quote(refs[child], safe="")))
        return total

    def _child_refs(self, model: TaggedPOWL, path: str) -> Dict[TaggedPOWL, str]:
        children = list(getattr(model, "children", []))
        refs: Dict[TaggedPOWL, str] = {}
        seen = set()
        for index, child in enumerate(children):
            raw = child.attributes.get("execution_id")
            if raw is None:
                if self._config.require_stable_ids:
                    raise _AdmissionError(
                        Standing.REFUSED,
                        RefusalCode.UNSTABLE_IDENTITY,
                        "%s child %d is missing attributes['execution_id']" % (path, index),
                    )
                ref = "n%d" % index
            elif not isinstance(raw, str) or not raw.strip():
                raise _AdmissionError(
                    Standing.REFUSED,
                    RefusalCode.UNSTABLE_IDENTITY,
                    "%s child execution_id must be a non-empty string" % path,
                )
            else:
                ref = raw.strip()
            if ref in seen:
                raise _AdmissionError(
                    Standing.REFUSED,
                    RefusalCode.UNSTABLE_IDENTITY,
                    "%s contains duplicate execution_id %r" % (path, ref),
                )
            seen.add(ref)
            refs[child] = ref
        return refs

    def _model_digest_for(self, model: TaggedPOWL) -> str:
        spec = self._model_spec(model, "root")
        encoded = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return self._sha256_text(encoded)

    def _model_spec(self, model: TaggedPOWL, path: str) -> Mapping[str, Any]:
        common = {
            "type": model.model_type.value,
            "min_freq": model.min_freq,
            "max_freq": model.max_freq,
            "attributes": dict(model.attributes),
        }
        if isinstance(model, Activity):
            common.update({
                "label": model.label,
                "organization": model.organization,
                "role": model.role,
            })
            return common
        refs = self._child_refs(model, path)
        children = {
            refs[child]: self._model_spec(child, "%s/%s" % (path, quote(refs[child], safe="")))
            for child in model.children
        }
        common["children"] = children
        common["edges"] = sorted((refs[u], refs[v]) for u, v in model.get_edges())
        if isinstance(model, ChoiceGraph):
            common["start_nodes"] = sorted(refs[node] for node in model.start_nodes())
            common["end_nodes"] = sorted(refs[node] for node in model.end_nodes())
        return common

    async def _execute_model(
        self,
        model: TaggedPOWL,
        path: str,
        inputs: Mapping[str, Any],
    ) -> _ModelResult:
        if self._is_cancelled():
            return _ModelResult(Standing.BLOCKED, reason="%s: run cancellation requested" % RefusalCode.CANCELLED.value)
        repeat = await self._resolve_repetitions(model, path)
        if isinstance(repeat, _ModelResult):
            return repeat
        if repeat == 0:
            return _ModelResult(Standing.ALIVE, output=[])
        outputs = []
        current_inputs = dict(inputs)
        for index in range(repeat):
            occurrence_path = path if repeat == 1 else "%s@%d" % (path, index)
            result = await self._execute_once(model, occurrence_path, current_inputs)
            if result.standing != Standing.ALIVE:
                return result
            outputs.append(result.output)
            current_inputs = {"previous_repeat": result.output, "initial": dict(inputs)}
        return _ModelResult(Standing.ALIVE, output=outputs[0] if repeat == 1 else outputs)

    async def _resolve_repetitions(self, model: TaggedPOWL, path: str) -> Any:
        if model.max_freq is not None and model.min_freq == model.max_freq:
            count = model.min_freq
            if count > self._config.max_repetitions:
                return _ModelResult(
                    Standing.REFUSED,
                    reason="%s: fixed repetition count exceeds max_repetitions" % RefusalCode.BOUND_EXCEEDED.value,
                )
            return count

        key = "%s/@repeat" % path
        existing = await self._store.load_step(self._current().run_id, key)
        if existing is not None:
            if existing.standing != Standing.ALIVE:
                return _ModelResult(existing.standing, reason=existing.reason)
            return int(existing.output["count"])

        claim = await self._claim_or_wait(key)
        if claim is not None:
            if claim.standing != Standing.ALIVE:
                return _ModelResult(claim.standing, reason=claim.reason)
            return int(claim.output["count"])

        started = time.time()
        decision = RepetitionDecision(
            key=key,
            min_freq=model.min_freq,
            max_freq=model.max_freq,
            model_type=model.model_type.value,
        )
        try:
            count = self._selection.repetitions(decision)
            if not isinstance(count, int):
                raise SelectionRefused(RefusalCode.INVALID_SELECTION, "repetition selection must be int")
            if count < model.min_freq:
                raise SelectionRefused(RefusalCode.INVALID_SELECTION, "repetition selection is below min_freq")
            if model.max_freq is not None and count > model.max_freq:
                raise SelectionRefused(RefusalCode.INVALID_SELECTION, "repetition selection exceeds max_freq")
            if count > self._config.max_repetitions:
                raise SelectionRefused(RefusalCode.BOUND_EXCEEDED, "repetition selection exceeds max_repetitions")
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.ALIVE,
                started=started,
                output={"count": count},
            )
            await self._store.save_step(receipt, self._current().owner)
            return count
        except SelectionRefused as exc:
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.REFUSED,
                started=started,
                reason="%s: %s" % (exc.code.value, exc.detail),
            )
            await self._store.save_step(receipt, self._current().owner)
            return _ModelResult(Standing.REFUSED, reason=receipt.reason)
        except Exception as exc:
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.BUILD_BROKEN,
                started=started,
                reason="selection policy raised %s: %s" % (type(exc).__name__, exc),
            )
            await self._store.save_step(receipt, self._current().owner)
            return _ModelResult(Standing.BUILD_BROKEN, reason=receipt.reason)

    async def _execute_once(self, model: TaggedPOWL, path: str, inputs: Mapping[str, Any]) -> _ModelResult:
        if isinstance(model, Activity):
            return await self._execute_activity(model, path, inputs)
        if isinstance(model, PartialOrder):
            return await self._execute_partial_order(model, path, inputs)
        if isinstance(model, ChoiceGraph):
            return await self._execute_choice_graph(model, path, inputs)
        return _ModelResult(
            Standing.UNSUPPORTED,
            reason="%s: unsupported model at execution" % RefusalCode.UNSUPPORTED_MODEL.value,
        )

    async def _execute_partial_order(
        self,
        model: PartialOrder,
        path: str,
        inputs: Mapping[str, Any],
    ) -> _ModelResult:
        refs = self._child_refs(model, path)
        pending = set(model.children)
        done: Dict[TaggedPOWL, _ModelResult] = {}
        while pending:
            if self._is_cancelled():
                return _ModelResult(Standing.BLOCKED, reason="%s: run cancellation requested" % RefusalCode.CANCELLED.value)
            ready = [node for node in pending if set(model.predecessors(node)).issubset(done.keys())]
            if not ready:
                return _ModelResult(Standing.BUILD_BROKEN, reason="partial-order scheduler reached an impossible state")
            ready.sort(key=lambda node: refs[node])
            tasks = []
            for node in ready:
                predecessor_outputs = {
                    refs[pred]: done[pred].output for pred in model.predecessors(node)
                }
                node_inputs = {
                    "root": dict(inputs),
                    "predecessors": predecessor_outputs,
                }
                child_path = "%s/%s" % (path, quote(refs[node], safe=""))
                tasks.append(self._execute_model(node, child_path, node_inputs))
            results = await asyncio.gather(*tasks)
            for node, result in zip(ready, results):
                done[node] = result
                pending.remove(node)
            failures = [result for result in results if result.standing != Standing.ALIVE]
            if failures:
                standing = self._worst_standing([result.standing for result in failures])
                reason = next((result.reason for result in failures if result.reason), None)
                return _ModelResult(standing, output={refs[n]: done[n].output for n in done}, reason=reason)
        return _ModelResult(Standing.ALIVE, output={refs[node]: done[node].output for node in model.children})

    async def _execute_choice_graph(
        self,
        model: ChoiceGraph,
        path: str,
        inputs: Mapping[str, Any],
    ) -> _ModelResult:
        refs = self._child_refs(model, path)
        candidates = list(model.start_nodes())
        can_end = False
        visit_counts: Dict[str, int] = {}
        outputs: List[Mapping[str, Any]] = []

        for decision_index in range(self._config.max_choice_steps + 1):
            if decision_index >= self._config.max_choice_steps:
                return _ModelResult(
                    Standing.REFUSED,
                    output=outputs,
                    reason="%s: max_choice_steps exceeded" % RefusalCode.BOUND_EXCEEDED.value,
                )
            selected = await self._resolve_choice(
                path=path,
                decision_index=decision_index,
                candidates=candidates,
                can_end=can_end,
                refs=refs,
            )
            if isinstance(selected, _ModelResult):
                selected.output = outputs
                return selected
            if selected is None:
                return _ModelResult(Standing.ALIVE, output=outputs)
            ref = refs[selected]
            visit = visit_counts.get(ref, 0)
            visit_counts[ref] = visit + 1
            child_path = "%s/%s@visit%d" % (path, quote(ref, safe=""), visit)
            child_inputs = {
                "root": dict(inputs),
                "choice_history": list(outputs),
            }
            result = await self._execute_model(selected, child_path, child_inputs)
            outputs.append({"node": ref, "output": result.output})
            if result.standing != Standing.ALIVE:
                return _ModelResult(result.standing, output=outputs, reason=result.reason)
            candidates = list(model.successors(selected))
            can_end = model.is_end(selected)
        return _ModelResult(Standing.BUILD_BROKEN, reason="choice scheduler fell through unexpectedly")

    async def _resolve_choice(
        self,
        *,
        path: str,
        decision_index: int,
        candidates: Sequence[TaggedPOWL],
        can_end: bool,
        refs: Mapping[TaggedPOWL, str],
    ) -> Any:
        key = "%s/@choice/%d" % (path, decision_index)
        existing = await self._store.load_step(self._current().run_id, key)
        if existing is not None:
            if existing.standing != Standing.ALIVE:
                return _ModelResult(existing.standing, reason=existing.reason)
            selected_ref = existing.output.get("selected")
            if selected_ref is None:
                if can_end:
                    return None
                return _ModelResult(Standing.BUILD_BROKEN, reason="persisted choice ended from a non-terminal state")
            selected = self._candidate_by_ref(candidates, refs, selected_ref)
            if selected is None:
                return _ModelResult(Standing.BUILD_BROKEN, reason="persisted choice does not match the admitted candidate set")
            return selected

        claim = await self._claim_or_wait(key)
        if claim is not None:
            if claim.standing != Standing.ALIVE:
                return _ModelResult(claim.standing, reason=claim.reason)
            selected_ref = claim.output.get("selected")
            if selected_ref is None:
                if can_end:
                    return None
                return _ModelResult(Standing.BUILD_BROKEN, reason="claimed choice ended from a non-terminal state")
            selected = self._candidate_by_ref(candidates, refs, selected_ref)
            if selected is None:
                return _ModelResult(Standing.BUILD_BROKEN, reason="claimed choice does not match the admitted candidate set")
            return selected

        started = time.time()
        ordered = sorted(candidates, key=lambda node: refs[node])
        decision = ChoiceDecision(
            key=key,
            candidates=tuple(
                ChoiceCandidate(
                    execution_id=refs[node],
                    model_type=node.model_type.value,
                    label=node.label if isinstance(node, Activity) else None,
                )
                for node in ordered
            ),
            can_end=can_end,
        )
        try:
            selected_ref = self._selection.choose(decision)
            if selected_ref is None:
                if not can_end:
                    raise SelectionRefused(RefusalCode.INVALID_SELECTION, "cannot end from this choice state")
                selected_node = None
            else:
                selected_node = self._candidate_by_ref(ordered, refs, selected_ref)
                if selected_node is None:
                    raise SelectionRefused(
                        RefusalCode.INVALID_SELECTION,
                        "selected execution_id %r is not an available candidate" % selected_ref,
                    )
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.ALIVE,
                started=started,
                output={"selected": selected_ref},
            )
            await self._store.save_step(receipt, self._current().owner)
            return selected_node
        except SelectionRefused as exc:
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.REFUSED,
                started=started,
                reason="%s: %s" % (exc.code.value, exc.detail),
            )
            await self._store.save_step(receipt, self._current().owner)
            return _ModelResult(Standing.REFUSED, reason=receipt.reason)
        except Exception as exc:
            receipt = self._internal_step(
                step_id=key,
                kind=StepKind.SELECTION,
                standing=Standing.BUILD_BROKEN,
                started=started,
                reason="selection policy raised %s: %s" % (type(exc).__name__, exc),
            )
            await self._store.save_step(receipt, self._current().owner)
            return _ModelResult(Standing.BUILD_BROKEN, reason=receipt.reason)

    def _candidate_by_ref(
        self,
        candidates: Iterable[TaggedPOWL],
        refs: Mapping[TaggedPOWL, str],
        selected_ref: str,
    ) -> Optional[TaggedPOWL]:
        for node in candidates:
            if refs[node] == selected_ref:
                return node
        return None

    async def _execute_activity(
        self,
        activity: Activity,
        path: str,
        inputs: Mapping[str, Any],
    ) -> _ModelResult:
        existing = await self._store.load_step(self._current().run_id, path)
        if existing is not None:
            return _ModelResult(existing.standing, output=existing.output, reason=existing.reason)

        if activity.is_silent():
            claim = await self._claim_or_wait(path)
            if claim is not None:
                return _ModelResult(claim.standing, output=claim.output, reason=claim.reason)
            receipt = self._internal_step(
                step_id=path,
                kind=StepKind.SILENT,
                standing=Standing.ALIVE,
                started=time.time(),
                output=None,
            )
            await self._store.save_step(receipt, self._current().owner)
            return _ModelResult(Standing.ALIVE)

        idempotency_key = self._sha256_text("%s|%s|%s" % (self._current().run_id, self._current().model_digest, path))
        for attempt in range(1, self._config.retry.max_attempts + 1):
            attempt_id = "%s/@attempt/%d" % (path, attempt)
            prior = await self._store.load_step(self._current().run_id, attempt_id)
            if prior is not None:
                decision = await self._interpret_attempt(prior, path)
                if decision is not None:
                    return decision
                continue

            claim = await self._claim_or_wait(attempt_id)
            if claim is not None:
                decision = await self._interpret_attempt(claim, path)
                if decision is not None:
                    return decision
                continue

            started = time.time()
            command = ActivityCommand(
                run_id=self._current().run_id,
                workflow_id=self._current().workflow_id,
                model_digest=self._current().model_digest,
                step_id=path,
                idempotency_key=idempotency_key,
                attempt=attempt,
                label=activity.label or "",
                organization=activity.organization,
                role=activity.role,
                attributes=dict(activity.attributes),
                inputs=dict(inputs),
                variables=dict(self._current().variables),
            )
            try:
                async with self._semaphore:
                    external = await asyncio.wait_for(
                        self._call_actuator(command),
                        timeout=self._config.activity_timeout_seconds,
                    )
            except asyncio.TimeoutError:
                diagnostic = self._internal_step(
                    step_id=attempt_id,
                    kind=StepKind.DIAGNOSTIC,
                    standing=Standing.BLOCKED,
                    started=started,
                    reason="%s: actuator timed out; external consequence is unknown and will not be retried" % RefusalCode.TIMEOUT.value,
                )
                await self._store.save_step(diagnostic, self._current().owner)
                return await self._finalize_activity(path, diagnostic)
            except Exception as exc:
                diagnostic = self._internal_step(
                    step_id=attempt_id,
                    kind=StepKind.DIAGNOSTIC,
                    standing=Standing.BLOCKED,
                    started=started,
                    reason="%s: actuator raised %s; external consequence is unknown and will not be retried" % (
                        RefusalCode.UNRECEIPTED_ACTUATION.value,
                        type(exc).__name__,
                    ),
                    metadata={"error": str(exc)},
                )
                await self._store.save_step(diagnostic, self._current().owner)
                return await self._finalize_activity(path, diagnostic)

            validation_error = self._validate_external_receipt(external)
            if validation_error is not None:
                diagnostic = self._internal_step(
                    step_id=attempt_id,
                    kind=StepKind.DIAGNOSTIC,
                    standing=Standing.BLOCKED,
                    started=started,
                    reason="%s: %s" % (RefusalCode.UNRECEIPTED_ACTUATION.value, validation_error),
                )
                await self._store.save_step(diagnostic, self._current().owner)
                return await self._finalize_activity(path, diagnostic)

            attempt_receipt = StepReceipt(
                run_id=self._current().run_id,
                workflow_id=self._current().workflow_id,
                model_digest=self._current().model_digest,
                step_id=attempt_id,
                kind=StepKind.ACTIVITY_ATTEMPT,
                standing=external.standing,
                attempt=attempt,
                started_at=started,
                finished_at=time.time(),
                receipt_id=external.receipt_id,
                consequence_digest=external.consequence_digest or self._json_digest(external.output),
                reason=external.reason,
                output=external.output,
                metadata=dict(external.metadata, retryable=external.retryable),
            )
            await self._store.save_step(attempt_receipt, self._current().owner)

            if external.standing == Standing.ALIVE:
                return await self._finalize_activity(path, attempt_receipt)
            if external.standing == Standing.REFUSED:
                return await self._finalize_activity(path, attempt_receipt)
            if external.standing == Standing.BLOCKED and external.retryable and attempt < self._config.retry.max_attempts:
                await asyncio.sleep(self._config.retry.delay_for(attempt))
                continue
            return await self._finalize_activity(path, attempt_receipt)

        diagnostic = self._internal_step(
            step_id="%s/@retry-exhausted" % path,
            kind=StepKind.DIAGNOSTIC,
            standing=Standing.BLOCKED,
            started=time.time(),
            reason="%s: no receipted attempt reached ALIVE" % RefusalCode.RETRY_EXHAUSTED.value,
        )
        await self._store.save_step(diagnostic, self._current().owner)
        return await self._finalize_activity(path, diagnostic)

    async def _interpret_attempt(self, receipt: StepReceipt, path: str) -> Optional[_ModelResult]:
        if receipt.standing in (Standing.ALIVE, Standing.REFUSED):
            return await self._finalize_activity(path, receipt)
        retryable = bool(receipt.metadata.get("retryable"))
        if receipt.standing == Standing.BLOCKED and retryable:
            return None
        return await self._finalize_activity(path, receipt)

    async def _finalize_activity(self, path: str, attempt_receipt: StepReceipt) -> _ModelResult:
        existing = await self._store.load_step(self._current().run_id, path)
        if existing is not None:
            return _ModelResult(existing.standing, output=existing.output, reason=existing.reason)
        claim = await self._claim_or_wait(path)
        if claim is not None:
            return _ModelResult(claim.standing, output=claim.output, reason=claim.reason)
        summary = StepReceipt(
            run_id=self._current().run_id,
            workflow_id=self._current().workflow_id,
            model_digest=self._current().model_digest,
            step_id=path,
            kind=StepKind.ACTIVITY,
            standing=attempt_receipt.standing,
            attempt=attempt_receipt.attempt,
            started_at=attempt_receipt.started_at,
            finished_at=time.time(),
            receipt_id=self._internal_receipt_id(path, attempt_receipt.receipt_id or "diagnostic"),
            consequence_digest=attempt_receipt.consequence_digest,
            reason=attempt_receipt.reason,
            output=attempt_receipt.output,
            metadata={"source_step": attempt_receipt.step_id, "external_receipt_id": attempt_receipt.receipt_id},
        )
        await self._store.save_step(summary, self._current().owner)
        return _ModelResult(summary.standing, output=summary.output, reason=summary.reason)

    async def _call_actuator(self, command: ActivityCommand) -> ActuationReceipt:
        method = self._actuator.actuate
        if inspect.iscoroutinefunction(method):
            result = await method(command)
        else:
            result = await asyncio.to_thread(method, command)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _validate_external_receipt(self, receipt: Any) -> Optional[str]:
        if not isinstance(receipt, ActuationReceipt):
            return "actuator must return ActuationReceipt"
        if not receipt.receipt_id or not isinstance(receipt.receipt_id, str):
            return "actuator receipt_id must be a non-empty string"
        if receipt.standing not in (Standing.ALIVE, Standing.BLOCKED, Standing.REFUSED):
            return "actuator standing must be ALIVE, BLOCKED, or REFUSED"
        if receipt.retryable and receipt.standing != Standing.BLOCKED:
            return "only BLOCKED receipts may be retryable"
        return None

    async def _claim_or_wait(self, step_id: str) -> Optional[StepReceipt]:
        deadline = time.monotonic() + self._config.claim_wait_seconds
        while True:
            claim = await self._store.claim_step(
                self._current().run_id,
                step_id,
                self._current().owner,
                self._config.claim_lease_seconds,
            )
            if claim.state == ClaimState.ACQUIRED:
                return None
            if claim.state == ClaimState.COMPLETED:
                return claim.receipt
            if time.monotonic() >= deadline:
                return StepReceipt(
                    run_id=self._current().run_id,
                    workflow_id=self._current().workflow_id,
                    model_digest=self._current().model_digest,
                    step_id=step_id,
                    kind=StepKind.DIAGNOSTIC,
                    standing=Standing.BLOCKED,
                    attempt=0,
                    started_at=time.time(),
                    finished_at=time.time(),
                    reason="%s: step lease remained busy" % RefusalCode.CLAIM_CONFLICT.value,
                )
            await asyncio.sleep(self._config.claim_poll_seconds)

    def _internal_step(
        self,
        *,
        step_id: str,
        kind: StepKind,
        standing: Standing,
        started: float,
        output: Any = None,
        reason: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> StepReceipt:
        consequence_digest = self._json_digest(output)
        return StepReceipt(
            run_id=self._current().run_id,
            workflow_id=self._current().workflow_id,
            model_digest=self._current().model_digest,
            step_id=step_id,
            kind=kind,
            standing=standing,
            attempt=0,
            started_at=started,
            finished_at=time.time(),
            receipt_id=self._internal_receipt_id(step_id, consequence_digest or standing.value),
            consequence_digest=consequence_digest,
            reason=reason,
            output=output,
            metadata=dict(metadata or {}),
        )

    def _internal_receipt_id(self, step_id: str, material: str) -> str:
        return "powl:%s" % self._sha256_text("%s|%s|%s|%s" % (
            self._current().run_id,
            self._current().model_digest,
            step_id,
            material,
        ))

    def _receipt_digest(self, steps: Sequence[StepReceipt]) -> str:
        payload = [
            {
                "step_id": step.step_id,
                "kind": step.kind.value,
                "standing": step.standing.value,
                "attempt": step.attempt,
                "receipt_id": step.receipt_id,
                "consequence_digest": step.consequence_digest,
                "reason": step.reason,
            }
            for step in sorted(steps, key=lambda item: item.step_id)
        ]
        return self._sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def _json_digest(self, value: Any) -> Optional[str]:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        return self._sha256_text(encoded)

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _current(self) -> _RunContext:
        return self._context.get()

    def _is_cancelled(self) -> bool:
        context = self._current()
        return context.cancel_event is not None and context.cancel_event.is_set()

    @staticmethod
    def _worst_standing(standings: Sequence[Standing]) -> Standing:
        order = {
            Standing.UNKNOWN: 0,
            Standing.ALIVE: 1,
            Standing.PARTIAL_ALIVE: 2,
            Standing.UNSUPPORTED: 3,
            Standing.BLOCKED: 4,
            Standing.BUILD_BROKEN: 5,
            Standing.REFUSED: 6,
        }
        return max(standings, key=lambda standing: order.get(standing, 0))

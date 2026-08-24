from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import get_ident
from time import monotonic_ns
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from SpiffWorkflow import Workflow
from SpiffWorkflow.specs.Join import Join
from SpiffWorkflow.specs.Simple import Simple
from SpiffWorkflow.specs.WorkflowSpec import WorkflowSpec
from SpiffWorkflow.util.task import TaskState

from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.base import TaggedPOWL
from powl.objects.tagged_powl.choice_graph import ChoiceGraph
from powl.objects.tagged_powl.partial_order import PartialOrder


ActivityHandler = Callable[[Activity], Any]


class UnsupportedPOWLExecution(ValueError):
    """Raised when execution would require semantics not admitted by this adapter."""


class POWLExecutionError(RuntimeError):
    """Raised when an admitted POWL activity fails during execution."""

    def __init__(self, activity: Activity, cause: BaseException) -> None:
        label = "τ" if activity.is_silent() else activity.label
        super().__init__(f"POWL activity {label!r} failed: {cause}")
        self.activity = activity
        self.__cause__ = cause


@dataclass(frozen=True)
class ActivityExecution:
    activity: Activity
    started_ns: int
    finished_ns: int
    thread_id: int
    result: Any


@dataclass(frozen=True)
class ExecutionReceipt:
    executions: Tuple[ActivityExecution, ...]

    def for_activity(self, activity: Activity) -> ActivityExecution:
        for execution in self.executions:
            if execution.activity is activity:
                return execution
        raise KeyError(activity)


@dataclass(frozen=True)
class _Block:
    entries: Tuple[Simple, ...]
    exits: Tuple[Simple, ...]


class SpiffPOWLExecutor:
    """Execute POWL partial orders using SpiffWorkflow as the state machine.

    POWL remains authoritative for precedence. SpiffWorkflow advances workflow
    state and exposes the currently READY frontier. Observable activity handlers
    run in worker threads; all Spiff task-tree mutation stays on the coordinator
    thread.
    """

    def __init__(self, *, max_workers: Optional[int] = None) -> None:
        if max_workers is not None and max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers
        self._counter = 0
        self._activities_by_spec: Dict[str, Activity] = {}

    def execute(self, model: TaggedPOWL, handler: ActivityHandler) -> ExecutionReceipt:
        self._counter = 0
        self._activities_by_spec = {}
        self._admit(model)

        spec = WorkflowSpec(name="POWL automatic concurrency", addstart=True)
        block = self._compile(model, spec)
        for entry in block.entries:
            spec.start.connect(entry)

        errors = spec.validate()
        if errors:
            raise UnsupportedPOWLExecution("SpiffWorkflow rejected compiled POWL: " + "; ".join(errors))

        workflow = Workflow(spec)
        workflow.run_all(halt_on_manual=True)

        receipts = []
        in_flight: Dict[Future[ActivityExecution], Tuple[Any, Activity]] = {}
        submitted_task_ids = set()

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="powl") as pool:
            while True:
                for task in workflow.get_tasks(state=TaskState.READY):
                    activity = self._activities_by_spec.get(task.task_spec.name)
                    if activity is None or task.id in submitted_task_ids:
                        continue
                    submitted_task_ids.add(task.id)
                    future = pool.submit(self._run_activity, activity, handler)
                    in_flight[future] = (task, activity)

                if not in_flight:
                    workflow.run_all(halt_on_manual=True)
                    if workflow.is_completed():
                        break
                    ready_observable = [
                        task for task in workflow.get_tasks(state=TaskState.READY)
                        if task.task_spec.name in self._activities_by_spec
                        and task.id not in submitted_task_ids
                    ]
                    if ready_observable:
                        continue
                    raise UnsupportedPOWLExecution(
                        "Compiled workflow made no progress and exposed no executable POWL activities"
                    )

                done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
                for future in done:
                    task, activity = in_flight.pop(future)
                    try:
                        execution = future.result()
                    except BaseException as exc:
                        workflow.cancel(success=False)
                        for pending in in_flight:
                            pending.cancel()
                        raise POWLExecutionError(activity, exc) from exc

                    receipts.append(execution)
                    task.run()
                    workflow.run_all(halt_on_manual=True)

        receipts.sort(key=lambda item: (item.started_ns, item.finished_ns, item.thread_id))
        return ExecutionReceipt(tuple(receipts))

    def _admit(self, model: TaggedPOWL) -> None:
        if model.min_freq != 1 or model.max_freq != 1:
            raise UnsupportedPOWLExecution(
                "Spiff execution currently admits only exact-once POWL nodes; "
                "expand/resolve frequency semantics before actuation"
            )
        if isinstance(model, Activity):
            return
        if isinstance(model, PartialOrder):
            model.validate()
            for child in model.children:
                self._admit(child)
            return
        if isinstance(model, ChoiceGraph):
            raise UnsupportedPOWLExecution(
                "ChoiceGraph execution requires an explicit choice policy; "
                "choice is not reinterpreted as concurrency"
            )
        raise UnsupportedPOWLExecution(f"Unsupported POWL node type: {type(model).__name__}")

    def _compile(self, model: TaggedPOWL, spec: WorkflowSpec) -> _Block:
        if isinstance(model, Activity):
            name = self._next_name("activity")
            task = Simple(spec, name, manual=not model.is_silent())
            if not model.is_silent():
                self._activities_by_spec[name] = model
            return _Block((task,), (task,))

        if not isinstance(model, PartialOrder):
            raise UnsupportedPOWLExecution(f"Unsupported POWL node type: {type(model).__name__}")

        children = tuple(model.children)
        if not children:
            noop = Simple(spec, self._next_name("empty"), manual=False)
            return _Block((noop,), (noop,))

        child_blocks = {child: self._compile(child, spec) for child in children}
        child_order = {child: index for index, child in enumerate(children)}
        entries = []
        exits = []

        for child in children:
            predecessors = tuple(sorted(model.predecessors(child), key=child_order.__getitem__))
            successors = tuple(model.successors(child))
            child_block = child_blocks[child]

            if not predecessors:
                entries.extend(child_block.entries)
            else:
                predecessor_exits = self._stable_unique(
                    exit_task
                    for predecessor in predecessors
                    for exit_task in child_blocks[predecessor].exits
                )
                if len(predecessor_exits) == 1:
                    upstream = predecessor_exits[0]
                    for entry in child_block.entries:
                        upstream.connect(entry)
                else:
                    join = Join(spec, self._next_name("join"))
                    for upstream in predecessor_exits:
                        upstream.connect(join)
                    for entry in child_block.entries:
                        join.connect(entry)

            if not successors:
                exits.extend(child_block.exits)

        return _Block(tuple(self._stable_unique(entries)), tuple(self._stable_unique(exits)))

    def _next_name(self, kind: str) -> str:
        self._counter += 1
        return f"__powl_{kind}_{self._counter:06d}"

    @staticmethod
    def _stable_unique(values: Iterable[Simple]) -> list[Simple]:
        result = []
        seen = set()
        for value in values:
            if value.name in seen:
                continue
            seen.add(value.name)
            result.append(value)
        return result

    @staticmethod
    def _run_activity(activity: Activity, handler: ActivityHandler) -> ActivityExecution:
        started_ns = monotonic_ns()
        result = handler(activity)
        finished_ns = monotonic_ns()
        return ActivityExecution(
            activity=activity,
            started_ns=started_ns,
            finished_ns=finished_ns,
            thread_id=get_ident(),
            result=result,
        )

import asyncio

from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.choice_graph import ChoiceGraph
from powl.objects.tagged_powl.partial_order import PartialOrder
from powl.runtime import (
    ActuationReceipt,
    InMemoryRunStore,
    RetryPolicy,
    RunnerConfig,
    Standing,
    TableSelectionPolicy,
    WorkflowRunner,
)


def activity(name, execution_id=None, **attrs):
    attributes = dict(attrs)
    if execution_id is not None:
        attributes["execution_id"] = execution_id
    return Activity(label=name, attributes=attributes)


class RecordingActuator:
    def __init__(self, behavior=None, delay=0):
        self.commands = []
        self.behavior = behavior
        self.delay = delay

    async def actuate(self, command):
        self.commands.append(command)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behavior:
            return self.behavior(command, len(self.commands))
        return ActuationReceipt(
            receipt_id="external:%s:%d" % (command.run_id, len(self.commands)),
            standing=Standing.ALIVE,
            output={"label": command.label, "run": command.run_id, "variables": dict(command.variables)},
        )


def run(coro):
    return asyncio.run(coro)


def test_admission_refuses_unstable_composite_child_identity():
    a = activity("A")
    b = activity("B")
    model = PartialOrder(nodes=[a, b], edges=[(a, b)])
    receipt = run(WorkflowRunner(RecordingActuator()).run(model, run_id="r", workflow_id="w"))
    assert receipt.standing == Standing.REFUSED
    assert "UNSTABLE_IDENTITY" in receipt.reason


def test_partial_order_executes_ready_wave_and_passes_predecessor_receipts():
    a = activity("A", "a")
    b = activity("B", "b")
    c = activity("C", "c")
    model = PartialOrder(nodes=[a, b, c], edges=[(a, c), (b, c)])
    actuator = RecordingActuator(delay=0.01)
    receipt = run(WorkflowRunner(actuator).run(model, run_id="po", workflow_id="wf"))
    assert receipt.standing == Standing.ALIVE
    assert {command.label for command in actuator.commands[:2]} == {"A", "B"}
    c_command = next(command for command in actuator.commands if command.label == "C")
    assert set(c_command.inputs["predecessors"]) == {"a", "b"}
    assert len([step for step in receipt.steps if step.kind.value == "activity"]) == 3


def test_exact_run_replay_never_reactuates():
    store = InMemoryRunStore()
    actuator = RecordingActuator()
    model = activity("A")
    runner = WorkflowRunner(actuator, store=store)
    first = run(runner.run(model, run_id="replay", workflow_id="wf"))
    second = run(runner.run(model, run_id="replay", workflow_id="wf"))
    assert first.standing == Standing.ALIVE
    assert second.standing == Standing.ALIVE
    assert second.replayed is True
    assert len(actuator.commands) == 1
    assert second.receipt_digest == first.receipt_digest


def test_ambiguous_choice_refuses_before_do():
    a = activity("A", "a")
    b = activity("B", "b")
    model = ChoiceGraph(nodes=[a, b], start_nodes=[a, b], end_nodes=[a, b])
    actuator = RecordingActuator()
    receipt = run(WorkflowRunner(actuator).run(model, run_id="choice-refuse", workflow_id="wf"))
    assert receipt.standing == Standing.REFUSED
    assert "AMBIGUOUS_SELECTION" in receipt.reason
    assert actuator.commands == []


def test_explicit_choice_table_selects_one_path():
    a = activity("A", "a")
    b = activity("B", "b")
    model = ChoiceGraph(nodes=[a, b], start_nodes=[a, b], end_nodes=[a, b])
    selection = TableSelectionPolicy(choices={"root/@choice/0": "b", "root/@choice/1": None})
    actuator = RecordingActuator()
    receipt = run(WorkflowRunner(actuator, selection_policy=selection).run(model, run_id="choice", workflow_id="wf"))
    assert receipt.standing == Standing.ALIVE
    assert [command.label for command in actuator.commands] == ["B"]
    choice_steps = [step for step in receipt.steps if step.kind.value == "selection"]
    assert [step.output["selected"] for step in choice_steps] == ["b", None]


def test_retry_requires_receipted_retryable_block():
    def behavior(command, call):
        if call == 1:
            return ActuationReceipt(
                receipt_id="external:block",
                standing=Standing.BLOCKED,
                retryable=True,
                reason="transient",
            )
        return ActuationReceipt(receipt_id="external:ok", standing=Standing.ALIVE, output={"ok": True})

    actuator = RecordingActuator(behavior)
    config = RunnerConfig(retry=RetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0))
    receipt = run(WorkflowRunner(actuator, config=config).run(activity("A"), run_id="retry", workflow_id="wf"))
    assert receipt.standing == Standing.ALIVE
    assert len(actuator.commands) == 2
    assert actuator.commands[0].idempotency_key == actuator.commands[1].idempotency_key
    attempts = [step for step in receipt.steps if step.kind.value == "activity_attempt"]
    assert [step.standing for step in attempts] == [Standing.BLOCKED, Standing.ALIVE]


def test_unreceipted_exception_blocks_without_retry():
    class Failing:
        def __init__(self):
            self.calls = 0

        async def actuate(self, command):
            self.calls += 1
            raise RuntimeError("transport vanished after DO")

    actuator = Failing()
    config = RunnerConfig(retry=RetryPolicy(max_attempts=5, base_delay_seconds=0, max_delay_seconds=0))
    receipt = run(WorkflowRunner(actuator, config=config).run(activity("A"), run_id="exception", workflow_id="wf"))
    assert receipt.standing == Standing.BLOCKED
    assert actuator.calls == 1
    assert "UNRECEIPTED_ACTUATION" in receipt.reason


def test_run_id_cannot_be_rebound_to_different_subject():
    store = InMemoryRunStore()
    actuator = RecordingActuator()
    runner = WorkflowRunner(actuator, store=store)
    first = run(runner.run(activity("A"), run_id="same", workflow_id="wf"))
    second = run(runner.run(activity("B"), run_id="same", workflow_id="wf"))
    assert first.standing == Standing.ALIVE
    assert second.standing == Standing.REFUSED
    assert "RUN_ID_REUSE" in second.reason
    assert len(actuator.commands) == 1


def test_one_runner_is_safe_for_concurrent_independent_runs():
    actuator = RecordingActuator(delay=0.02)
    runner = WorkflowRunner(actuator)
    model = activity("A")

    async def execute():
        return await asyncio.gather(
            runner.run(model, run_id="c1", workflow_id="wf1", variables={"tenant": 1}),
            runner.run(model, run_id="c2", workflow_id="wf2", variables={"tenant": 2}),
        )

    receipts = run(execute())
    assert [receipt.standing for receipt in receipts] == [Standing.ALIVE, Standing.ALIVE]
    observed = {(c.run_id, c.workflow_id, c.variables["tenant"]) for c in actuator.commands}
    assert observed == {("c1", "wf1", 1), ("c2", "wf2", 2)}

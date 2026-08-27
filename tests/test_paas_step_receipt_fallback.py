from types import SimpleNamespace

from powl.paas import ReceiptReplayActuator


def test_step_receipt_is_used_when_attempt_receipt_is_absent():
    command = SimpleNamespace(run_id="run-1", model_digest="sha256:model", step_id="root", attempt=3)
    actuator = ReceiptReplayActuator({"root": {"receipt_id": "step", "standing": "ALIVE"}})
    assert actuator.actuate(command).receipt_id == "step"

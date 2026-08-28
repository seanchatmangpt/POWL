from types import SimpleNamespace

from powl.paas import ReceiptReplayActuator


def test_attempt_specific_receipt_precedes_step_fallback():
    command = SimpleNamespace(run_id="run-1", model_digest="sha256:model", step_id="root", attempt=2)
    actuator = ReceiptReplayActuator({"root": {"receipt_id": "step", "standing": "ALIVE"}, "root@2": {"receipt_id": "attempt", "standing": "ALIVE"}})
    assert actuator.actuate(command).receipt_id == "attempt"

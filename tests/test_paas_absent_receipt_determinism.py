from types import SimpleNamespace

from powl.paas import ReceiptReplayActuator


def test_absent_receipt_refusal_identity_is_deterministic():
    command = SimpleNamespace(run_id="run-1", model_digest="sha256:model", step_id="root", attempt=1)
    actuator = ReceiptReplayActuator()
    assert actuator.actuate(command).receipt_id == actuator.actuate(command).receipt_id

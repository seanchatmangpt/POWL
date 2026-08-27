from types import SimpleNamespace

from powl.paas import ReceiptReplayActuator


def test_absent_receipt_records_absence_evidence_metadata():
    command = SimpleNamespace(run_id="run-1", model_digest="sha256:model", step_id="root", attempt=1)
    receipt = ReceiptReplayActuator().actuate(command)
    assert receipt.metadata["execution_mode"] == "REPLAY_ONLY"
    assert receipt.metadata["evidence_kind"] == "absence"

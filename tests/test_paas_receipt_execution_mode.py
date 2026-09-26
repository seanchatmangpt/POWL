from powl.paas import _receipt_from_manifest


def test_replay_receipt_forces_replay_execution_mode_metadata():
    receipt = _receipt_from_manifest({"receipt_id": "r-1", "standing": "ALIVE", "metadata": {"execution_mode": "DO"}}, "root")
    assert receipt.metadata["execution_mode"] == "REPLAY_ONLY"
    assert receipt.metadata["evidence_kind"] == "replay_manifest"

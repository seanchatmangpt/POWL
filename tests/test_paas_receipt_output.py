from powl.paas import _receipt_from_manifest


def test_replay_receipt_preserves_output():
    receipt = _receipt_from_manifest({"receipt_id": "r-1", "standing": "ALIVE", "output": {"plan_id": "p-1"}}, "root")
    assert receipt.output == {"plan_id": "p-1"}

from powl.paas import _receipt_from_manifest


def test_replay_receipt_preserves_reason():
    receipt = _receipt_from_manifest({"receipt_id": "r-1", "standing": "REFUSED", "reason": "policy denied"}, "root")
    assert receipt.reason == "policy denied"

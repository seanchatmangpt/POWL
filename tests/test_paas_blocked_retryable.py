from powl.paas import _receipt_from_manifest


def test_blocked_receipt_may_be_retryable():
    receipt = _receipt_from_manifest({"receipt_id": "r-1", "standing": "BLOCKED", "retryable": True}, "root")
    assert receipt.standing.value == "BLOCKED"
    assert receipt.retryable is True

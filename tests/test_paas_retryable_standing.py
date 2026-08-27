import pytest

from powl.paas import ProtocolError, _receipt_from_manifest


def test_only_blocked_receipt_may_be_retryable():
    with pytest.raises(ProtocolError, match="only BLOCKED may be retryable"):
        _receipt_from_manifest({"receipt_id": "r-1", "standing": "ALIVE", "retryable": True}, "root")

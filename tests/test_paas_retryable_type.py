import pytest

from powl.paas import ProtocolError, _receipt_from_manifest


def test_retryable_must_be_boolean():
    with pytest.raises(ProtocolError, match="retryable must be boolean"):
        _receipt_from_manifest({"receipt_id": "r-1", "standing": "BLOCKED", "retryable": "yes"}, "root")

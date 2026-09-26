import pytest

from powl.paas import ProtocolError, _receipt_from_manifest


def test_replay_receipt_rejects_invalid_standing():
    with pytest.raises(ProtocolError, match="standing is invalid"):
        _receipt_from_manifest({"receipt_id": "r-1", "standing": "UNKNOWN"}, "root")

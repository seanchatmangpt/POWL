import pytest

from powl.paas import ProtocolError, _receipt_from_manifest


def test_replay_receipt_requires_identity():
    with pytest.raises(ProtocolError, match="receipt_id is required"):
        _receipt_from_manifest({"standing": "ALIVE"}, "root")

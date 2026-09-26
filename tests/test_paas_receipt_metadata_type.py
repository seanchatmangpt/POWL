import pytest

from powl.paas import ProtocolError, _receipt_from_manifest


def test_receipt_metadata_must_be_object():
    with pytest.raises(ProtocolError, match="metadata must be an object"):
        _receipt_from_manifest({"receipt_id": "r-1", "standing": "ALIVE", "metadata": []}, "root")

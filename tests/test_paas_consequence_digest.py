from powl.paas import _receipt_from_manifest


def test_replay_receipt_preserves_consequence_digest():
    receipt = _receipt_from_manifest({"receipt_id": "r-1", "standing": "ALIVE", "consequence_digest": "sha256:abc"}, "root")
    assert receipt.consequence_digest == "sha256:abc"

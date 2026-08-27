import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_model_document_must_be_object():
    with pytest.raises(ProtocolError, match="model_document must be a POWL JSON object"):
        asyncio.run(execute_request({"run_id": "run-1", "workflow_id": "wf-1", "model_document": []}))

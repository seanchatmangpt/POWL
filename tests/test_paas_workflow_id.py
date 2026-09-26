import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_workflow_id_is_required():
    with pytest.raises(ProtocolError, match="workflow_id must be a non-empty string"):
        asyncio.run(execute_request({"run_id": "run-1", "workflow_id": ""}))

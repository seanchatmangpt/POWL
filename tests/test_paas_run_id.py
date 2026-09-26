import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_run_id_is_required():
    with pytest.raises(ProtocolError, match="run_id must be a non-empty string"):
        asyncio.run(execute_request({"run_id": ""}))

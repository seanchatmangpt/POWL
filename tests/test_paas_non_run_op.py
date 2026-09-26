import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_non_run_operation_is_refused_before_execution():
    with pytest.raises(ProtocolError, match="only op='run' is admitted"):
        asyncio.run(execute_request({"op": "deploy"}))

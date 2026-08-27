import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_wrong_protocol_is_refused_before_execution():
    with pytest.raises(ProtocolError, match="protocol must be"):
        asyncio.run(execute_request({"protocol": "powl-paas/0"}))

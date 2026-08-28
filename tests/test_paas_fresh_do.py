import asyncio

import pytest

from powl.paas import ProtocolError, execute_request


def test_fresh_do_mode_is_refused():
    with pytest.raises(ProtocolError, match="fresh DO is not available"):
        asyncio.run(execute_request({"execution_mode": "DO"}))

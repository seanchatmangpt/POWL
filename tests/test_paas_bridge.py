import asyncio

from powl.paas import execute_request


def _request(model):
    return {
        "protocol": "powl-paas/1",
        "op": "run",
        "execution_mode": "REPLAY_ONLY",
        "run_id": "run-1",
        "workflow_id": "workflow-1",
        "model_document": {
            "format": "powl-json",
            "format_version": "1.0",
            "model": model,
        },
    }


def test_silent_model_executes_without_actuation():
    result = asyncio.run(execute_request(_request({"type": "activity", "label": None})))

    assert result["execution_mode"] == "REPLAY_ONLY"
    assert result["receipt"]["standing"] == "ALIVE"
    assert result["receipt"]["steps"][0]["kind"] == "silent"
    assert result["receipt"]["receipt_digest"]


def test_observable_activity_without_receipt_is_lawfully_refused():
    result = asyncio.run(execute_request(_request({"type": "activity", "label": "Ship"})))

    assert result["receipt"]["standing"] == "REFUSED"
    assert "REPLAY_ONLY cannot perform fresh DO" in result["receipt"]["reason"]


def test_observable_activity_replays_admitted_receipt():
    request = _request({"type": "activity", "label": "Ship"})
    request["activity_receipts"] = {
        "root": {
            "receipt_id": "external:ship:1",
            "standing": "ALIVE",
            "output": {"shipment_id": "S-1"},
            "consequence_digest": "sha256:consequence",
        }
    }

    result = asyncio.run(execute_request(request))

    assert result["receipt"]["standing"] == "ALIVE"
    attempt = next(step for step in result["receipt"]["steps"] if step["kind"] == "activity_attempt")
    assert attempt["receipt_id"] == "external:ship:1"
    assert attempt["metadata"]["evidence_kind"] == "replay_manifest"


def test_composite_json_ids_become_stable_runtime_execution_ids():
    request = _request(
        {
            "type": "partial_order",
            "nodes": [
                {"id": "a", "type": "activity", "label": None},
                {"id": "b", "type": "activity", "label": None},
            ],
            "edges": [{"source": "a", "target": "b"}],
        }
    )

    result = asyncio.run(execute_request(request))

    assert result["receipt"]["standing"] == "ALIVE"
    step_ids = {step["step_id"] for step in result["receipt"]["steps"]}
    assert "root/a" in step_ids
    assert "root/b" in step_ids

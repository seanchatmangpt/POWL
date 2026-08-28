"""POWL PaaS protocol bridge.

The bridge executes the canonical Python POWL runtime in REPLAY_ONLY mode. It
never shells out to arbitrary user commands and never fabricates an ALIVE
external actuation. Observable activities must be backed by an admitted
ActuationReceipt supplied in the replay manifest; missing evidence is a lawful
REFUSED result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from powl.io.powl_json import from_powl_json_dict
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.choice_graph import ChoiceGraph
from powl.objects.tagged_powl.partial_order import PartialOrder
from powl.runtime import ActuationReceipt, Standing, TableSelectionPolicy, WorkflowRunner

PROTOCOL = "powl-paas/1"
EXECUTION_MODE = "REPLAY_ONLY"


class ProtocolError(ValueError):
    pass


class ReceiptReplayActuator:
    """Receipt-only actuator: verify/replay evidence, never create a consequence."""

    def __init__(self, manifest: Optional[Mapping[str, Mapping[str, Any]]] = None) -> None:
        self._manifest = dict(manifest or {})

    def actuate(self, command: Any) -> ActuationReceipt:
        key = f"{command.step_id}@{command.attempt}"
        raw = self._manifest.get(key, self._manifest.get(command.step_id))
        if raw is None:
            material = f"{command.run_id}|{command.model_digest}|{command.step_id}|no-receipt"
            return ActuationReceipt(
                receipt_id="powl:refusal:" + hashlib.sha256(material.encode("utf-8")).hexdigest(),
                standing=Standing.REFUSED,
                reason=(
                    "ADMISSION: no admitted external receipt for step "
                    f"{command.step_id!r}; REPLAY_ONLY cannot perform fresh DO"
                ),
                metadata={"execution_mode": EXECUTION_MODE, "evidence_kind": "absence"},
            )
        return _receipt_from_manifest(raw, command.step_id)


def _receipt_from_manifest(raw: Mapping[str, Any], step_id: str) -> ActuationReceipt:
    if not isinstance(raw, Mapping):
        raise ProtocolError(f"activity_receipts[{step_id!r}] must be an object")
    receipt_id = raw.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ProtocolError(f"activity_receipts[{step_id!r}].receipt_id is required")
    try:
        standing = Standing(raw.get("standing"))
    except ValueError as exc:
        raise ProtocolError(f"activity_receipts[{step_id!r}].standing is invalid") from exc
    if standing not in {Standing.ALIVE, Standing.BLOCKED, Standing.REFUSED}:
        raise ProtocolError(
            f"activity_receipts[{step_id!r}].standing must be ALIVE, BLOCKED, or REFUSED"
        )
    retryable = raw.get("retryable", False)
    if not isinstance(retryable, bool):
        raise ProtocolError(f"activity_receipts[{step_id!r}].retryable must be boolean")
    if retryable and standing is not Standing.BLOCKED:
        raise ProtocolError(f"activity_receipts[{step_id!r}] only BLOCKED may be retryable")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ProtocolError(f"activity_receipts[{step_id!r}].metadata must be an object")
    return ActuationReceipt(
        receipt_id=receipt_id,
        standing=standing,
        output=raw.get("output"),
        retryable=retryable,
        consequence_digest=raw.get("consequence_digest"),
        metadata=dict(metadata, execution_mode=EXECUTION_MODE, evidence_kind="replay_manifest"),
        reason=raw.get("reason"),
    )


def _require_string(request: Mapping[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{key} must be a non-empty string")
    return value


def _attach_execution_ids(model: Any, spec: Mapping[str, Any]) -> None:
    """Bind POWL JSON child IDs to runtime execution_id without changing file semantics."""
    if isinstance(model, Activity):
        return
    if not isinstance(model, (PartialOrder, ChoiceGraph)):
        return
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != len(model.children):
        raise ProtocolError("model_document nodes do not match decoded POWL children")
    for child, child_spec in zip(model.children, nodes):
        if not isinstance(child_spec, Mapping):
            raise ProtocolError("model_document child must be an object")
        execution_id = child_spec.get("id")
        if not isinstance(execution_id, str) or not execution_id:
            raise ProtocolError("every composite child requires a stable id")
        child.attributes = dict(child.attributes)
        child.attributes["execution_id"] = execution_id
        _attach_execution_ids(child, child_spec)


def _selection_policy(request: Mapping[str, Any]) -> TableSelectionPolicy:
    repetitions = request.get("repetitions", {})
    choices = request.get("choices", {})
    if not isinstance(repetitions, Mapping) or not isinstance(choices, Mapping):
        raise ProtocolError("repetitions and choices must be objects")
    return TableSelectionPolicy(repetitions=repetitions, choices=choices)


def _step_to_dict(step: Any) -> dict[str, Any]:
    return {
        "run_id": step.run_id,
        "workflow_id": step.workflow_id,
        "model_digest": step.model_digest,
        "step_id": step.step_id,
        "kind": step.kind.value,
        "standing": step.standing.value,
        "attempt": step.attempt,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "receipt_id": step.receipt_id,
        "consequence_digest": step.consequence_digest,
        "reason": step.reason,
        "output": step.output,
        "metadata": dict(step.metadata),
    }


def _run_to_dict(receipt: Any) -> dict[str, Any]:
    return {
        "run_id": receipt.run_id,
        "workflow_id": receipt.workflow_id,
        "model_digest": receipt.model_digest,
        "standing": receipt.standing.value,
        "started_at": receipt.started_at,
        "finished_at": receipt.finished_at,
        "receipt_digest": receipt.receipt_digest,
        "steps": [_step_to_dict(step) for step in receipt.steps],
        "reason": receipt.reason,
        "replayed": receipt.replayed,
    }


async def execute_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ProtocolError("request must be a JSON object")
    if request.get("protocol", PROTOCOL) != PROTOCOL:
        raise ProtocolError(f"protocol must be {PROTOCOL!r}")
    if request.get("op", "run") != "run":
        raise ProtocolError("only op='run' is admitted")
    if request.get("execution_mode", EXECUTION_MODE) != EXECUTION_MODE:
        raise ProtocolError("fresh DO is not available through the replay bridge")

    run_id = _require_string(request, "run_id")
    workflow_id = _require_string(request, "workflow_id")
    document = request.get("model_document")
    if not isinstance(document, Mapping):
        raise ProtocolError("model_document must be a POWL JSON object")

    parsed = from_powl_json_dict(document)
    _attach_execution_ids(parsed.model, document["model"])

    variables = request.get("variables", {})
    manifest = request.get("activity_receipts", {})
    if not isinstance(variables, Mapping) or not isinstance(manifest, Mapping):
        raise ProtocolError("variables and activity_receipts must be objects")

    runner = WorkflowRunner(
        ReceiptReplayActuator(manifest),
        selection_policy=_selection_policy(request),
    )
    receipt = await runner.run(
        parsed.model,
        run_id=run_id,
        workflow_id=workflow_id,
        variables=variables,
    )
    return {
        "protocol": PROTOCOL,
        "execution_mode": EXECUTION_MODE,
        "receipt": _run_to_dict(receipt),
    }


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "execution_mode": EXECUTION_MODE,
        "error": {
            "standing": "REFUSED",
            "code": "ADMISSION",
            "detail": str(exc),
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="POWL PaaS receipt/replay protocol bridge")
    parser.add_argument("--request", type=Path, required=True, help="Path to a JSON request")
    args = parser.parse_args(argv)
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        result = asyncio.run(execute_request(request))
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, ProtocolError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps(_error_payload(exc), sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

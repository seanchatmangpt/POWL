from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple

from .contracts import (
    BindResult,
    BindState,
    ClaimResult,
    ClaimState,
    RunBinding,
    RunReceipt,
    Standing,
    StepKind,
    StepReceipt,
)


class RunStore(Protocol):
    async def bind_run(self, binding: RunBinding) -> BindResult:
        ...

    async def load_run(self, run_id: str) -> Optional[RunReceipt]:
        ...

    async def save_run(self, receipt: RunReceipt) -> None:
        ...

    async def load_step(self, run_id: str, step_id: str) -> Optional[StepReceipt]:
        ...

    async def claim_step(
        self,
        run_id: str,
        step_id: str,
        owner: str,
        lease_seconds: float,
    ) -> ClaimResult:
        ...

    async def save_step(self, receipt: StepReceipt, owner: str) -> None:
        ...

    async def list_steps(self, run_id: str) -> List[StepReceipt]:
        ...


@dataclass
class _Lease:
    owner: str
    expires_at: float


class InMemoryRunStore:
    """Atomic reference store. Production adapters can back this protocol with SQL/KV storage."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bindings: Dict[str, RunBinding] = {}
        self._runs: Dict[str, RunReceipt] = {}
        self._steps: Dict[Tuple[str, str], StepReceipt] = {}
        self._leases: Dict[Tuple[str, str], _Lease] = {}

    async def bind_run(self, binding: RunBinding) -> BindResult:
        with self._lock:
            existing = self._bindings.get(binding.run_id)
            if existing is None:
                self._bindings[binding.run_id] = binding
                return BindResult(BindState.BOUND, binding, self._runs.get(binding.run_id))
            if existing.workflow_id != binding.workflow_id or existing.model_digest != binding.model_digest:
                return BindResult(BindState.CONFLICT, existing, self._runs.get(binding.run_id))
            return BindResult(BindState.EXISTING, existing, self._runs.get(binding.run_id))

    async def load_run(self, run_id: str) -> Optional[RunReceipt]:
        with self._lock:
            return self._runs.get(run_id)

    async def save_run(self, receipt: RunReceipt) -> None:
        with self._lock:
            self._runs[receipt.run_id] = receipt

    async def load_step(self, run_id: str, step_id: str) -> Optional[StepReceipt]:
        with self._lock:
            return self._steps.get((run_id, step_id))

    async def claim_step(
        self,
        run_id: str,
        step_id: str,
        owner: str,
        lease_seconds: float,
    ) -> ClaimResult:
        key = (run_id, step_id)
        now = time.monotonic()
        with self._lock:
            completed = self._steps.get(key)
            if completed is not None:
                return ClaimResult(ClaimState.COMPLETED, completed)
            lease = self._leases.get(key)
            if lease is not None and lease.owner != owner:
                if lease.expires_at > now:
                    return ClaimResult(ClaimState.BUSY)
                binding = self._bindings.get(run_id)
                material = "%s|%s|ABANDONED_CLAIM" % (run_id, step_id)
                digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
                receipt = StepReceipt(
                    run_id=run_id,
                    workflow_id=binding.workflow_id if binding else "",
                    model_digest=binding.model_digest if binding else "",
                    step_id=step_id,
                    kind=StepKind.DIAGNOSTIC,
                    standing=Standing.BLOCKED,
                    attempt=0,
                    started_at=time.time(),
                    finished_at=time.time(),
                    receipt_id="powl:%s" % digest,
                    reason=(
                        "ABANDONED_CLAIM: previous worker lease expired without a persisted "
                        "receipt; external consequence is unknown and the step will not be re-actuated"
                    ),
                )
                self._steps[key] = receipt
                self._leases.pop(key, None)
                return ClaimResult(ClaimState.COMPLETED, receipt)
            self._leases[key] = _Lease(owner=owner, expires_at=now + lease_seconds)
            return ClaimResult(ClaimState.ACQUIRED)

    async def save_step(self, receipt: StepReceipt, owner: str) -> None:
        key = (receipt.run_id, receipt.step_id)
        with self._lock:
            lease = self._leases.get(key)
            if lease is None:
                raise RuntimeError("step claim is not held")
            if lease.owner != owner:
                raise RuntimeError("step lease is owned by another runner")
            self._steps[key] = receipt
            self._leases.pop(key, None)

    async def list_steps(self, run_id: str) -> List[StepReceipt]:
        with self._lock:
            receipts = [receipt for (rid, _), receipt in self._steps.items() if rid == run_id]
        return sorted(receipts, key=lambda item: item.step_id)

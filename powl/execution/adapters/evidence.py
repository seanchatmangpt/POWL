"""Minimal evidence-recording surface for the bindings adapter.

This is the ENTIRE adapter surface for evidence recording -- one
``typing.Protocol`` with one method. No OCEL import anywhere in this file
(or anywhere in ``powl/execution/`` core): a real OCEL-backed recorder
satisfies this protocol structurally, by having a matching ``record``
method, without this package ever importing OCEL types or declaring OCEL as
a dependency. A real, hand-written, in-memory recorder (e.g. one backed by a
plain Python list, as used in this package's own tests) satisfies it just
as well -- ``EvidenceRecorder`` names a shape, not a specific backend.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from ...objects.tagged_powl.base import TaggedPOWL

__all__ = ["EvidenceRecorder"]


@runtime_checkable
class EvidenceRecorder(Protocol):
    """Structural protocol for recording one real fired step's outcome.

    ``record`` is invoked once per real fired step (success or error),
    sequentially, in real deterministic fire order -- see
    ``adapters.bindings.replay_with_bindings`` for exactly when and how.
    """

    def record(
        self, activity: str, node: TaggedPOWL, outcome: Mapping[str, Any]
    ) -> None:
        ...

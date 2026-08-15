from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..objects.tagged_powl.base import TaggedPOWL


@dataclass(frozen=True, slots=True)
class Marking:
    """
    Real token state for a POWL 2.0 replay.

    ``active`` is the set of TaggedPOWL nodes whose occurrence is currently
    open (has fired, has not yet completed its own repeat budget). Node
    identity follows TaggedPOWL's own identity-based equality/hash (see
    ``objects/tagged_powl/base.py``), so a Marking is only ever meaningful
    relative to the specific model instance it was produced against.

    ``completed_counts`` is the real, per-node occurrence count observed so
    far in this replay -- the only source of truth for min_freq/max_freq
    enforcement. Never re-derived from anything else (no re-counting from a
    trace, no inference from graph shape).
    """

    active: frozenset[TaggedPOWL] = frozenset()
    completed_counts: Mapping[TaggedPOWL, int] = field(default_factory=dict)

    def with_active(self, node: TaggedPOWL) -> "Marking":
        return Marking(active=self.active | {node}, completed_counts=self.completed_counts)

    def with_completed(self, node: TaggedPOWL) -> "Marking":
        counts = dict(self.completed_counts)
        counts[node] = counts.get(node, 0) + 1
        return Marking(active=self.active - {node}, completed_counts=counts)

    def count_of(self, node: TaggedPOWL) -> int:
        return self.completed_counts.get(node, 0)

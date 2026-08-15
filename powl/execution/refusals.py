"""Named refusal vocabulary for :mod:`powl.execution.engine`.

Every :class:`~powl.execution.engine.ExecutionRefusal` raised by the real
engine names a specific violation via this enum -- never a bare string.
Members here are exactly the cases ``engine.py`` itself raises today (see
each ``REFUSED:`` call site) plus two reserved for this workflow's later
phases: ``TRANSITION_BUDGET_EXHAUSTED`` (the transition-budget name for the
same concept as ``MAX_STEPS_EXCEEDED`` -- reuse that member, not a
duplicate) and ``CONFORMANCE_DIVERGENCE`` (for the conformance-checker
phase, not yet raised anywhere in this repo).

Shape only borrowed from ``autofde_lab.powl.refusals.PowlRefusal`` (a
StrEnum of named refusal reasons); no code copied, and this enum's members
are scoped to TaggedPOWL's simpler model, not that package's larger
vocabulary.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PowlRefusal"]


class PowlRefusal(StrEnum):
    """Named reasons :class:`~powl.execution.engine.ExecutionRefusal` is raised."""

    NO_START_NODES = "NO_START_NODES"
    CHOOSER_RETURNED_UNOFFERED_OPTION = "CHOOSER_RETURNED_UNOFFERED_OPTION"
    CHOICE_GRAPH_DISCONNECTED = "CHOICE_GRAPH_DISCONNECTED"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    UNSUPPORTED_NODE_TYPE = "UNSUPPORTED_NODE_TYPE"

    #: Not yet raised in engine.py; reserved for a future transition-budget
    #: phase. Same concept as MAX_STEPS_EXCEEDED -- reuse that member for
    #: the step-budget refusal engine.py raises today, do not use this one
    #: for it.
    TRANSITION_BUDGET_EXHAUSTED = "TRANSITION_BUDGET_EXHAUSTED"

    #: Not yet raised anywhere in this repo; reserved for the conformance
    #: checker phase.
    CONFORMANCE_DIVERGENCE = "CONFORMANCE_DIVERGENCE"

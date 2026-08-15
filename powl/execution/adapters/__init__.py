"""Opt-in adapters on top of ``powl.execution``'s core engine.

Deliberate asymmetry, stated explicitly: ``powl/execution/__init__.py`` (the
core package) does NOT import or re-export anything from this
``adapters`` subpackage, and nothing under ``powl/execution/`` outside this
subpackage imports from it either. The core engine (``engine.py``,
``marking.py``, ``refusals.py``, ``conformance.py``) stays dependency-free
and minimal-surface by design -- it knows nothing about action bindings,
evidence recording, or OCEL.

Callers who want that behavior opt in explicitly, one import at a time, e.g.::

    from powl.execution.adapters.bindings import replay_with_bindings
    from powl.execution.adapters.evidence import EvidenceRecorder

This subpackage is real, thin, additive layering on top of the core
engine's own public hooks (``replay_concurrent``'s ``on_fire`` parameter) --
it does not reimplement or fork any firing/concurrency logic, and it still
imports zero OCEL types (see ``evidence.py``): a real OCEL-backed recorder,
or any other object, satisfies ``EvidenceRecorder`` structurally just by
having a matching ``record`` method, with no dependency edge from this
package to OCEL at all.
"""

from __future__ import annotations

__all__: list[str] = []

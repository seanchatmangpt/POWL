from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import networkx as nx

from powl.execution import ExecutionReceipt, SpiffPOWLExecutor

from .togaf import (
    ADMPhase,
    ArchitectureAdmissionError,
    ArchitectureContract,
    ArchitecturePlan,
    WorkPackage,
    compile_togaf_plan,
)


class ArchitectureLayer(str, Enum):
    BUSINESS = "business"
    DATA = "data"
    APPLICATION = "application"
    TECHNOLOGY = "technology"


class BuildingBlockKind(str, Enum):
    ABB = "architecture-building-block"
    SBB = "solution-building-block"


@dataclass(frozen=True)
class BuildingBlock:
    id: str
    name: str
    layer: ArchitectureLayer
    kind: BuildingBlockKind
    version: str = "1"
    realizes: FrozenSet[str] = field(default_factory=frozenset)
    depends_on: FrozenSet[str] = field(default_factory=frozenset)
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
    controls: FrozenSet[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ArchitectureState:
    id: str
    building_blocks: Tuple[BuildingBlock, ...]
    controls: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _validate_state(self)

    @property
    def blocks(self) -> Mapping[str, BuildingBlock]:
        return {block.id: block for block in self.building_blocks}

    @property
    def capabilities(self) -> FrozenSet[str]:
        capabilities = set()
        for block in self.building_blocks:
            capabilities.update(block.capabilities)
        return frozenset(capabilities)

    @property
    def unrealized_abbs(self) -> Tuple[str, ...]:
        realized = set()
        for block in self.building_blocks:
            if block.kind == BuildingBlockKind.SBB:
                realized.update(block.realizes)
        return tuple(
            sorted(
                block.id
                for block in self.building_blocks
                if block.kind == BuildingBlockKind.ABB and block.id not in realized
            )
        )

    @property
    def realization_coverage(self) -> float:
        abbs = [
            block
            for block in self.building_blocks
            if block.kind == BuildingBlockKind.ABB
        ]
        if not abbs:
            return 1.0
        return (len(abbs) - len(self.unrealized_abbs)) / len(abbs)


@dataclass(frozen=True)
class ArchitectureDelta:
    added: Tuple[BuildingBlock, ...] = ()
    removed: Tuple[BuildingBlock, ...] = ()
    changed: Tuple[Tuple[BuildingBlock, BuildingBlock], ...] = ()
    capabilities_added: FrozenSet[str] = field(default_factory=frozenset)
    capabilities_removed: FrozenSet[str] = field(default_factory=frozenset)
    controls_added: FrozenSet[str] = field(default_factory=frozenset)
    controls_removed: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.changed
            or self.capabilities_added
            or self.capabilities_removed
            or self.controls_added
            or self.controls_removed
        )


@dataclass(frozen=True)
class TransitionArchitecture:
    baseline: ArchitectureState
    target: ArchitectureState
    delta: ArchitectureDelta
    plan: ArchitecturePlan

    @property
    def concurrency_width(self) -> int:
        return self.plan.concurrency_width

    @property
    def critical_path_length(self) -> int:
        return self.plan.critical_path_length


@dataclass(frozen=True)
class ArchitectureRevision:
    state: ArchitectureState
    fingerprint: str
    parent_id: Optional[str] = None


class ArchitectureRepository:
    """Small append-only architecture repository with explicit lineage."""

    def __init__(self) -> None:
        self._revisions: Dict[str, ArchitectureRevision] = {}

    def commit(
        self,
        state: ArchitectureState,
        *,
        parent_id: Optional[str] = None,
    ) -> ArchitectureRevision:
        if state.id in self._revisions:
            raise ArchitectureAdmissionError(
                "DUPLICATE_ARCHITECTURE_STATE",
                f"Architecture state {state.id!r} already exists.",
            )
        if parent_id is not None and parent_id not in self._revisions:
            raise ArchitectureAdmissionError(
                "UNKNOWN_ARCHITECTURE_PARENT",
                f"Unknown parent architecture state: {parent_id}",
            )
        revision = ArchitectureRevision(
            state=state,
            fingerprint=architecture_state_fingerprint(state),
            parent_id=parent_id,
        )
        self._revisions[state.id] = revision
        return revision

    def get(self, state_id: str) -> ArchitectureRevision:
        try:
            return self._revisions[state_id]
        except KeyError as exc:
            raise ArchitectureAdmissionError(
                "UNKNOWN_ARCHITECTURE_STATE",
                f"Unknown architecture state: {state_id}",
            ) from exc

    def history(self, state_id: str) -> Tuple[ArchitectureRevision, ...]:
        history = []
        revision = self.get(state_id)
        while True:
            history.append(revision)
            if revision.parent_id is None:
                break
            revision = self.get(revision.parent_id)
        history.reverse()
        return tuple(history)


class DriftKind(str, Enum):
    MISSING_BLOCK = "missing-block"
    UNEXPECTED_BLOCK = "unexpected-block"
    BLOCK_CHANGED = "block-changed"
    STATE_CONTROL_MISSING = "state-control-missing"
    STATE_CONTROL_UNEXPECTED = "state-control-unexpected"


@dataclass(frozen=True)
class DriftFinding:
    kind: DriftKind
    subject_id: str
    expected: Optional[str] = None
    observed: Optional[str] = None


@dataclass(frozen=True)
class DriftReport:
    target_id: str
    observed_id: str
    findings: Tuple[DriftFinding, ...]

    @property
    def is_conformant(self) -> bool:
        return len(self.findings) == 0

    @property
    def severity(self) -> int:
        return len(self.findings)


@dataclass(frozen=True)
class ActuationAuthorization:
    plan_fingerprint: str
    admitted_work_package_ids: FrozenSet[str]


def compare_architecture_states(
    baseline: ArchitectureState,
    target: ArchitectureState,
) -> ArchitectureDelta:
    baseline_blocks = baseline.blocks
    target_blocks = target.blocks

    baseline_ids = set(baseline_blocks)
    target_ids = set(target_blocks)

    added = tuple(target_blocks[block_id] for block_id in sorted(target_ids - baseline_ids))
    removed = tuple(
        baseline_blocks[block_id] for block_id in sorted(baseline_ids - target_ids)
    )
    changed = tuple(
        (baseline_blocks[block_id], target_blocks[block_id])
        for block_id in sorted(baseline_ids & target_ids)
        if baseline_blocks[block_id] != target_blocks[block_id]
    )

    return ArchitectureDelta(
        added=added,
        removed=removed,
        changed=changed,
        capabilities_added=target.capabilities.difference(baseline.capabilities),
        capabilities_removed=baseline.capabilities.difference(target.capabilities),
        controls_added=target.controls.difference(baseline.controls),
        controls_removed=baseline.controls.difference(target.controls),
    )


def compile_transition_architecture(
    baseline: ArchitectureState,
    target: ArchitectureState,
    *,
    contract: Optional[ArchitectureContract] = None,
) -> TransitionArchitecture:
    delta = compare_architecture_states(baseline, target)
    changed_target = {after.id: after for _, after in delta.changed}
    added_target = {block.id: block for block in delta.added}
    active_target = dict(added_target)
    active_target.update(changed_target)

    removed_baseline = {block.id: block for block in delta.removed}
    changed_ids = set(changed_target)
    added_ids = set(added_target)
    removed_ids = set(removed_baseline)

    packages = []

    for block_id in sorted(active_target):
        block = active_target[block_id]
        dependency_packages = {
            _change_package_id(dependency_id, added_ids, changed_ids)
            for dependency_id in block.depends_on
            if dependency_id in added_ids or dependency_id in changed_ids
        }
        packages.append(
            WorkPackage(
                id=_change_package_id(block_id, added_ids, changed_ids),
                name=(
                    f"Deploy {block.name}"
                    if block_id in added_ids
                    else f"Change {block.name}"
                ),
                phase=_phase_for_layer(block.layer),
                depends_on=frozenset(dependency_packages),
                controls=block.controls,
            )
        )

    baseline_dependents = _reverse_dependencies(baseline)
    for block_id in sorted(removed_baseline):
        block = removed_baseline[block_id]
        dependent_retirements = {
            f"retire:{dependent_id}"
            for dependent_id in baseline_dependents.get(block_id, frozenset())
            if dependent_id in removed_ids
        }
        packages.append(
            WorkPackage(
                id=f"retire:{block_id}",
                name=f"Retire {block.name}",
                phase=_phase_for_layer(block.layer),
                depends_on=frozenset(dependent_retirements),
                controls=block.controls,
            )
        )

    plan = compile_togaf_plan(tuple(packages), contract=contract)
    return TransitionArchitecture(
        baseline=baseline,
        target=target,
        delta=delta,
        plan=plan,
    )


def detect_architecture_drift(
    target: ArchitectureState,
    observed: ArchitectureState,
) -> DriftReport:
    target_blocks = target.blocks
    observed_blocks = observed.blocks
    target_ids = set(target_blocks)
    observed_ids = set(observed_blocks)

    findings = []

    for block_id in sorted(target_ids - observed_ids):
        findings.append(
            DriftFinding(
                DriftKind.MISSING_BLOCK,
                block_id,
                expected=_block_signature(target_blocks[block_id]),
            )
        )
    for block_id in sorted(observed_ids - target_ids):
        findings.append(
            DriftFinding(
                DriftKind.UNEXPECTED_BLOCK,
                block_id,
                observed=_block_signature(observed_blocks[block_id]),
            )
        )
    for block_id in sorted(target_ids & observed_ids):
        if target_blocks[block_id] != observed_blocks[block_id]:
            findings.append(
                DriftFinding(
                    DriftKind.BLOCK_CHANGED,
                    block_id,
                    expected=_block_signature(target_blocks[block_id]),
                    observed=_block_signature(observed_blocks[block_id]),
                )
            )

    for control in sorted(target.controls.difference(observed.controls)):
        findings.append(
            DriftFinding(
                DriftKind.STATE_CONTROL_MISSING,
                control,
                expected="present",
                observed="absent",
            )
        )
    for control in sorted(observed.controls.difference(target.controls)):
        findings.append(
            DriftFinding(
                DriftKind.STATE_CONTROL_UNEXPECTED,
                control,
                expected="absent",
                observed="present",
            )
        )

    return DriftReport(
        target_id=target.id,
        observed_id=observed.id,
        findings=tuple(findings),
    )


def compile_drift_remediation(
    target: ArchitectureState,
    observed: ArchitectureState,
    *,
    contract: Optional[ArchitectureContract] = None,
) -> TransitionArchitecture:
    return compile_transition_architecture(
        observed,
        target,
        contract=contract,
    )


def architecture_state_fingerprint(state: ArchitectureState) -> str:
    payload = {
        "id": state.id,
        "controls": sorted(state.controls),
        "blocks": [
            _block_payload(block)
            for block in sorted(state.building_blocks, key=lambda item: item.id)
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def architecture_plan_fingerprint(plan: ArchitecturePlan) -> str:
    payload = [
        {
            "id": package.id,
            "name": package.name,
            "phase": package.phase.value,
            "depends_on": sorted(package.depends_on),
            "closes_gap_ids": sorted(package.closes_gap_ids),
            "controls": sorted(package.controls),
            "organization": package.organization,
            "role": package.role,
        }
        for package in sorted(plan.work_packages, key=lambda item: item.id)
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def authorize_architecture_plan(plan: ArchitecturePlan) -> ActuationAuthorization:
    return ActuationAuthorization(
        plan_fingerprint=architecture_plan_fingerprint(plan),
        admitted_work_package_ids=frozenset(
            package.id for package in plan.work_packages
        ),
    )


def execute_architecture_plan(
    plan: ArchitecturePlan,
    actuator: Callable[[WorkPackage], Any],
    *,
    authorization: ActuationAuthorization,
    max_workers: Optional[int] = None,
) -> ExecutionReceipt:
    fingerprint = architecture_plan_fingerprint(plan)
    if authorization.plan_fingerprint != fingerprint:
        raise ArchitectureAdmissionError(
            "PLAN_FINGERPRINT_MISMATCH",
            "Actuation authorization does not match the architecture plan.",
        )

    plan_ids = frozenset(package.id for package in plan.work_packages)
    if authorization.admitted_work_package_ids != plan_ids:
        missing = sorted(plan_ids.difference(authorization.admitted_work_package_ids))
        extra = sorted(authorization.admitted_work_package_ids.difference(plan_ids))
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise ArchitectureAdmissionError(
            "ACTUATION_SCOPE_MISMATCH",
            "Actuation authorization scope must exactly match the admitted plan"
            + ("; " + "; ".join(details) if details else ""),
        )

    package_by_id = {package.id: package for package in plan.work_packages}

    def handler(activity):
        package_id = activity.get_attribute("architecture.work_package_id")
        if package_id not in package_by_id:
            raise ArchitectureAdmissionError(
                "UNRECEIPTED_ACTIVITY",
                f"POWL activity is not bound to an admitted work package: {package_id}",
            )
        return actuator(package_by_id[package_id])

    return SpiffPOWLExecutor(max_workers=max_workers).execute(plan.model, handler)


def architecture_to_turtle(state: ArchitectureState) -> str:
    """Deterministic RDF projection using public provenance/metadata vocabularies."""

    lines = [
        "@prefix arch: <urn:powl:architecture:> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "",
    ]

    state_uri = _state_uri(state.id)
    lines.extend(
        [
            f"<{state_uri}> a prov:Collection ;",
            f"    dcterms:identifier {_literal(state.id)} ;",
            f"    arch:fingerprint {_literal(architecture_state_fingerprint(state))} .",
            "",
        ]
    )

    for control in sorted(state.controls):
        lines.append(
            f"<{state_uri}> arch:control {_literal(control)} ."
        )

    if state.controls:
        lines.append("")

    for block in sorted(state.building_blocks, key=lambda item: item.id):
        block_uri = _block_uri(block.id)
        rdf_type = (
            "arch:ArchitectureBuildingBlock"
            if block.kind == BuildingBlockKind.ABB
            else "arch:SolutionBuildingBlock"
        )
        lines.extend(
            [
                f"<{state_uri}> prov:hadMember <{block_uri}> .",
                f"<{block_uri}> a prov:Entity, {rdf_type} ;",
                f"    dcterms:identifier {_literal(block.id)} ;",
                f"    skos:prefLabel {_literal(block.name)} ;",
                f"    arch:layer {_literal(block.layer.value)} ;",
                f"    arch:version {_literal(block.version)} .",
            ]
        )
        for target_id in sorted(block.realizes):
            lines.append(
                f"<{block_uri}> arch:realizes <{_block_uri(target_id)}> ."
            )
        for dependency_id in sorted(block.depends_on):
            lines.append(
                f"<{block_uri}> arch:dependsOn <{_block_uri(dependency_id)}> ."
            )
        for capability in sorted(block.capabilities):
            lines.append(
                f"<{block_uri}> arch:capability {_literal(capability)} ."
            )
        for control in sorted(block.controls):
            lines.append(
                f"<{block_uri}> arch:control {_literal(control)} ."
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _validate_state(state: ArchitectureState) -> None:
    if not state.id:
        raise ArchitectureAdmissionError(
            "EMPTY_ARCHITECTURE_STATE_ID",
            "Architecture state ID must be non-empty.",
        )

    blocks = {}
    for block in state.building_blocks:
        if not block.id:
            raise ArchitectureAdmissionError(
                "EMPTY_BUILDING_BLOCK_ID",
                "Architecture building block IDs must be non-empty.",
            )
        if block.id in blocks:
            raise ArchitectureAdmissionError(
                "DUPLICATE_BUILDING_BLOCK",
                f"Duplicate architecture building block ID: {block.id}",
            )
        blocks[block.id] = block

    known = set(blocks)
    graph = nx.DiGraph()
    graph.add_nodes_from(known)

    for block in blocks.values():
        if block.id in block.depends_on:
            raise ArchitectureAdmissionError(
                "SELF_DEPENDENT_BUILDING_BLOCK",
                f"Building block {block.id!r} depends on itself.",
            )
        unknown_dependencies = block.depends_on.difference(known)
        if unknown_dependencies:
            raise ArchitectureAdmissionError(
                "UNKNOWN_BUILDING_BLOCK_DEPENDENCY",
                f"Building block {block.id!r} references unknown dependencies: "
                + ", ".join(sorted(unknown_dependencies)),
            )
        for dependency_id in block.depends_on:
            graph.add_edge(dependency_id, block.id)

        unknown_realizations = block.realizes.difference(known)
        if unknown_realizations:
            raise ArchitectureAdmissionError(
                "UNKNOWN_REALIZATION_TARGET",
                f"Building block {block.id!r} realizes unknown ABBs: "
                + ", ".join(sorted(unknown_realizations)),
            )
        if block.kind == BuildingBlockKind.ABB and block.realizes:
            raise ArchitectureAdmissionError(
                "ABB_CANNOT_REALIZE",
                f"Architecture building block {block.id!r} cannot realize another ABB.",
            )
        for target_id in block.realizes:
            if blocks[target_id].kind != BuildingBlockKind.ABB:
                raise ArchitectureAdmissionError(
                    "INVALID_REALIZATION_TARGET",
                    f"Solution building block {block.id!r} must realize ABBs; "
                    f"{target_id!r} is not an ABB.",
                )

    if not nx.is_directed_acyclic_graph(graph):
        raise ArchitectureAdmissionError(
            "CYCLIC_BUILDING_BLOCK_DEPENDENCY",
            "Architecture building block dependencies must be acyclic.",
        )


def _phase_for_layer(layer: ArchitectureLayer) -> ADMPhase:
    if layer == ArchitectureLayer.BUSINESS:
        return ADMPhase.B
    if layer in (ArchitectureLayer.DATA, ArchitectureLayer.APPLICATION):
        return ADMPhase.C
    return ADMPhase.D


def _change_package_id(
    block_id: str,
    added_ids: Iterable[str],
    changed_ids: Iterable[str],
) -> str:
    if block_id in added_ids:
        return f"deploy:{block_id}"
    if block_id in changed_ids:
        return f"change:{block_id}"
    raise ArchitectureAdmissionError(
        "UNMAPPED_TRANSITION_BLOCK",
        f"Building block {block_id!r} is not part of the transition delta.",
    )


def _reverse_dependencies(
    state: ArchitectureState,
) -> Mapping[str, FrozenSet[str]]:
    reverse: Dict[str, set] = {block.id: set() for block in state.building_blocks}
    for block in state.building_blocks:
        for dependency_id in block.depends_on:
            reverse[dependency_id].add(block.id)
    return {
        block_id: frozenset(dependents)
        for block_id, dependents in reverse.items()
    }


def _block_payload(block: BuildingBlock) -> Mapping[str, Any]:
    return {
        "id": block.id,
        "name": block.name,
        "layer": block.layer.value,
        "kind": block.kind.value,
        "version": block.version,
        "realizes": sorted(block.realizes),
        "depends_on": sorted(block.depends_on),
        "capabilities": sorted(block.capabilities),
        "controls": sorted(block.controls),
    }


def _block_signature(block: BuildingBlock) -> str:
    return json.dumps(
        _block_payload(block),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _state_uri(state_id: str) -> str:
    return "urn:powl:architecture:state:" + quote(state_id, safe="")


def _block_uri(block_id: str) -> str:
    return "urn:powl:architecture:block:" + quote(block_id, safe="")


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

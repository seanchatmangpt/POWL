from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple

import networkx as nx

from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.partial_order import PartialOrder


class ADMPhase(str, Enum):
    PRELIMINARY = "Preliminary"
    REQUIREMENTS = "Requirements"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"


class ArchitectureAdmissionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        work_package_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.work_package_id = work_package_id


@dataclass(frozen=True)
class CapabilityGap:
    id: str
    capability: str
    baseline: str
    target: str


@dataclass(frozen=True)
class WorkPackage:
    id: str
    name: str
    phase: ADMPhase
    depends_on: FrozenSet[str] = field(default_factory=frozenset)
    closes_gap_ids: FrozenSet[str] = field(default_factory=frozenset)
    controls: FrozenSet[str] = field(default_factory=frozenset)
    organization: Optional[str] = None
    role: Optional[str] = None


@dataclass(frozen=True)
class ArchitectureContract:
    name: str
    required_controls: FrozenSet[str] = field(default_factory=frozenset)
    package_controls: Tuple[Tuple[str, FrozenSet[str]], ...] = ()

    def controls_for(self, work_package_id: str) -> FrozenSet[str]:
        required = set(self.required_controls)
        for package_id, controls in self.package_controls:
            if package_id == work_package_id:
                required.update(controls)
        return frozenset(required)


@dataclass(frozen=True)
class ArchitecturePlan:
    model: PartialOrder
    work_packages: Tuple[WorkPackage, ...]
    activities: Mapping[str, Activity]
    concurrency_width: int
    critical_path_length: int
    dependency_edges_before_reduction: int
    dependency_edges_after_reduction: int

    @property
    def eliminated_dependency_edges(self) -> int:
        return self.dependency_edges_before_reduction - self.dependency_edges_after_reduction

    @property
    def initial_frontier(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                package_id
                for package_id, activity in self.activities.items()
                if self.model.in_degree(activity) == 0
            )
        )

    def ready_work_packages(self, completed_ids: Iterable[str]) -> Tuple[str, ...]:
        completed = set(completed_ids)
        unknown = completed.difference(self.activities)
        if unknown:
            raise ArchitectureAdmissionError(
                "UNKNOWN_COMPLETION",
                "Unknown completed work package(s): " + ", ".join(sorted(unknown)),
            )

        ready = []
        for package_id, activity in self.activities.items():
            if package_id in completed:
                continue
            predecessor_ids = {
                predecessor.get_attribute("architecture.work_package_id")
                for predecessor in self.model.predecessors(activity)
            }
            if predecessor_ids.issubset(completed):
                ready.append(package_id)
        return tuple(sorted(ready))


def compile_togaf_plan(
    work_packages: Sequence[WorkPackage],
    *,
    gaps: Sequence[CapabilityGap] = (),
    contract: Optional[ArchitectureContract] = None,
) -> ArchitecturePlan:
    packages = tuple(work_packages)
    package_by_id = _index_packages(packages)
    _validate_gaps(packages, gaps)
    _validate_contract(package_by_id, contract)
    _validate_dependencies(package_by_id)

    activities: Dict[str, Activity] = {}
    for package in packages:
        required_controls = (
            contract.controls_for(package.id) if contract is not None else frozenset()
        )
        missing_controls = required_controls.difference(package.controls)
        if missing_controls:
            raise ArchitectureAdmissionError(
                "MISSING_CONTROL",
                (
                    f"Work package {package.id!r} does not satisfy architecture "
                    f"contract {contract.name!r}; missing controls: "
                    + ", ".join(sorted(missing_controls))
                ),
                work_package_id=package.id,
            )

        activities[package.id] = Activity(
            label=package.name,
            organization=package.organization,
            role=package.role,
            attributes={
                "architecture.work_package_id": package.id,
                "architecture.adm_phase": package.phase.value,
                "architecture.depends_on": sorted(package.depends_on),
                "architecture.closes_gap_ids": sorted(package.closes_gap_ids),
                "architecture.controls": sorted(package.controls),
                "architecture.contract": contract.name if contract is not None else None,
            },
        )

    edges = []
    for package in packages:
        for dependency_id in sorted(package.depends_on):
            edges.append((activities[dependency_id], activities[package.id]))

    model = PartialOrder(nodes=activities.values(), edges=edges)
    try:
        model.validate()
    except ValueError as exc:
        raise ArchitectureAdmissionError(
            "CYCLIC_TRANSFORMATION",
            "Architecture work packages contain a dependency cycle.",
        ) from exc

    before = len(model.get_edges())
    model.validate_and_remove_transitive_edges()
    after = len(model.get_edges())

    graph = model.to_networkx()
    return ArchitecturePlan(
        model=model,
        work_packages=packages,
        activities=activities,
        concurrency_width=_dag_width(graph),
        critical_path_length=_critical_path_nodes(graph),
        dependency_edges_before_reduction=before,
        dependency_edges_after_reduction=after,
    )


def _index_packages(packages: Tuple[WorkPackage, ...]) -> Dict[str, WorkPackage]:
    result: Dict[str, WorkPackage] = {}
    for package in packages:
        if not package.id:
            raise ArchitectureAdmissionError(
                "EMPTY_WORK_PACKAGE_ID",
                "Architecture work package IDs must be non-empty.",
            )
        if package.id in result:
            raise ArchitectureAdmissionError(
                "DUPLICATE_WORK_PACKAGE",
                f"Duplicate architecture work package ID: {package.id}",
                work_package_id=package.id,
            )
        result[package.id] = package
    return result


def _validate_dependencies(package_by_id: Mapping[str, WorkPackage]) -> None:
    known = set(package_by_id)
    graph = nx.DiGraph()
    graph.add_nodes_from(known)

    for package in package_by_id.values():
        if package.id in package.depends_on:
            raise ArchitectureAdmissionError(
                "SELF_DEPENDENCY",
                f"Work package {package.id!r} depends on itself.",
                work_package_id=package.id,
            )
        unknown = package.depends_on.difference(known)
        if unknown:
            raise ArchitectureAdmissionError(
                "UNKNOWN_DEPENDENCY",
                (
                    f"Work package {package.id!r} references unknown dependencies: "
                    + ", ".join(sorted(unknown))
                ),
                work_package_id=package.id,
            )
        for dependency_id in package.depends_on:
            graph.add_edge(dependency_id, package.id)

    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        rendered = " -> ".join(str(edge[0]) for edge in cycle)
        if cycle:
            rendered += f" -> {cycle[0][0]}"
        raise ArchitectureAdmissionError(
            "CYCLIC_TRANSFORMATION",
            f"Architecture work packages contain a dependency cycle: {rendered}",
        )


def _validate_gaps(
    packages: Tuple[WorkPackage, ...],
    gaps: Sequence[CapabilityGap],
) -> None:
    gap_ids = set()
    for gap in gaps:
        if not gap.id:
            raise ArchitectureAdmissionError(
                "EMPTY_GAP_ID",
                "Capability gap IDs must be non-empty.",
            )
        if gap.id in gap_ids:
            raise ArchitectureAdmissionError(
                "DUPLICATE_GAP",
                f"Duplicate capability gap ID: {gap.id}",
            )
        gap_ids.add(gap.id)

    referenced = set()
    for package in packages:
        referenced.update(package.closes_gap_ids)

    unknown = referenced.difference(gap_ids)
    if unknown:
        raise ArchitectureAdmissionError(
            "UNKNOWN_GAP",
            "Work packages reference unknown capability gaps: "
            + ", ".join(sorted(unknown)),
        )


def _validate_contract(
    package_by_id: Mapping[str, WorkPackage],
    contract: Optional[ArchitectureContract],
) -> None:
    if contract is None:
        return

    known = set(package_by_id)
    declared = [package_id for package_id, _ in contract.package_controls]
    unknown = set(declared).difference(known)
    if unknown:
        raise ArchitectureAdmissionError(
            "UNKNOWN_CONTRACT_TARGET",
            "Architecture contract references unknown work packages: "
            + ", ".join(sorted(unknown)),
        )

    duplicates = sorted(
        package_id
        for package_id in set(declared)
        if declared.count(package_id) > 1
    )
    if duplicates:
        raise ArchitectureAdmissionError(
            "DUPLICATE_CONTRACT_TARGET",
            "Architecture contract repeats work package requirements: "
            + ", ".join(duplicates),
        )


def _critical_path_nodes(graph: nx.DiGraph) -> int:
    if graph.number_of_nodes() == 0:
        return 0
    return nx.dag_longest_path_length(graph) + 1


def _dag_width(graph: nx.DiGraph) -> int:
    if graph.number_of_nodes() == 0:
        return 0

    closure = nx.transitive_closure_dag(graph)
    left = [("left", node) for node in closure.nodes]
    right = [("right", node) for node in closure.nodes]

    bipartite = nx.Graph()
    bipartite.add_nodes_from(left, bipartite=0)
    bipartite.add_nodes_from(right, bipartite=1)
    for source, target in closure.edges:
        bipartite.add_edge(("left", source), ("right", target))

    matching = nx.algorithms.bipartite.maximum_matching(
        bipartite,
        top_nodes=set(left),
    )
    matched_left = sum(1 for node in left if node in matching)
    return graph.number_of_nodes() - matched_left

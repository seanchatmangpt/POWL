import threading

import pytest

from powl.enterprise.togaf import (
    ADMPhase,
    ArchitectureAdmissionError,
    ArchitectureContract,
    CapabilityGap,
    WorkPackage,
    compile_togaf_plan,
)
from powl.execution import SpiffPOWLExecutor


def _package(
    package_id,
    name,
    phase,
    *,
    depends_on=(),
    closes_gap_ids=(),
    controls=(),
):
    return WorkPackage(
        id=package_id,
        name=name,
        phase=phase,
        depends_on=frozenset(depends_on),
        closes_gap_ids=frozenset(closes_gap_ids),
        controls=frozenset(controls),
    )


def test_togaf_compiler_keeps_only_real_dependencies_and_maximizes_concurrency():
    gaps = (
        CapabilityGap("business-gap", "Order Management", "2", "5"),
        CapabilityGap("data-gap", "Customer Data", "2", "5"),
        CapabilityGap("technology-gap", "Runtime Platform", "2", "5"),
    )
    packages = (
        _package(
            "business",
            "Business Architecture",
            ADMPhase.B,
            closes_gap_ids=("business-gap",),
            controls=("architecture-approved",),
        ),
        _package(
            "data",
            "Data Architecture",
            ADMPhase.C,
            closes_gap_ids=("data-gap",),
            controls=("architecture-approved",),
        ),
        _package(
            "technology",
            "Technology Architecture",
            ADMPhase.D,
            closes_gap_ids=("technology-gap",),
            controls=("architecture-approved",),
        ),
        _package(
            "solutions",
            "Opportunities and Solutions",
            ADMPhase.E,
            depends_on=("business", "data", "technology"),
            controls=("architecture-approved",),
        ),
        _package(
            "migration",
            "Migration Planning",
            ADMPhase.F,
            depends_on=("business", "solutions"),
            controls=("architecture-approved",),
        ),
    )
    contract = ArchitectureContract(
        name="enterprise-architecture",
        required_controls=frozenset(("architecture-approved",)),
    )

    plan = compile_togaf_plan(packages, gaps=gaps, contract=contract)

    assert plan.initial_frontier == ("business", "data", "technology")
    assert plan.concurrency_width == 3
    assert plan.critical_path_length == 3
    assert plan.dependency_edges_before_reduction == 5
    assert plan.dependency_edges_after_reduction == 4
    assert plan.eliminated_dependency_edges == 1
    assert plan.ready_work_packages({"business"}) == ("data", "technology")


def test_togaf_contract_refuses_uncontrolled_actuation():
    packages = (
        _package(
            "data",
            "Data Architecture",
            ADMPhase.C,
            controls=("architecture-approved",),
        ),
    )
    contract = ArchitectureContract(
        name="regulated-data",
        required_controls=frozenset(("architecture-approved",)),
        package_controls=(
            ("data", frozenset(("privacy-reviewed", "residency-approved"))),
        ),
    )

    with pytest.raises(ArchitectureAdmissionError) as exc:
        compile_togaf_plan(packages, contract=contract)

    assert exc.value.code == "MISSING_CONTROL"
    assert exc.value.work_package_id == "data"
    assert "privacy-reviewed" in str(exc.value)
    assert "residency-approved" in str(exc.value)


def test_togaf_compiler_refuses_unknown_dependencies_and_cycles():
    with pytest.raises(ArchitectureAdmissionError) as unknown:
        compile_togaf_plan(
            (
                _package(
                    "migration",
                    "Migration",
                    ADMPhase.F,
                    depends_on=("missing",),
                ),
            )
        )
    assert unknown.value.code == "UNKNOWN_DEPENDENCY"

    with pytest.raises(ArchitectureAdmissionError) as cycle:
        compile_togaf_plan(
            (
                _package("a", "A", ADMPhase.A, depends_on=("b",)),
                _package("b", "B", ADMPhase.B, depends_on=("a",)),
            )
        )
    assert cycle.value.code == "CYCLIC_TRANSFORMATION"


def test_togaf_plan_executes_independent_architecture_work_concurrently():
    packages = (
        _package("business", "Business", ADMPhase.B),
        _package("data", "Data", ADMPhase.C),
        _package("technology", "Technology", ADMPhase.D),
        _package(
            "solutions",
            "Solutions",
            ADMPhase.E,
            depends_on=("business", "data", "technology"),
        ),
    )
    plan = compile_togaf_plan(packages)

    frontier = {"Business", "Data", "Technology"}
    barrier = threading.Barrier(3, timeout=5)
    completed = set()
    lock = threading.Lock()

    def handler(activity):
        if activity.label in frontier:
            barrier.wait()
            with lock:
                completed.add(activity.label)
            return activity.label
        assert activity.label == "Solutions"
        with lock:
            assert completed == frontier
        return activity.label

    receipt = SpiffPOWLExecutor(max_workers=3).execute(plan.model, handler)

    assert {execution.result for execution in receipt.executions} == {
        "Business",
        "Data",
        "Technology",
        "Solutions",
    }
    solution = receipt.for_activity(plan.activities["solutions"])
    solution_start = solution.started_ns
    for package_id in ("business", "data", "technology"):
        execution = receipt.for_activity(plan.activities[package_id])
        assert execution.finished_ns <= solution_start

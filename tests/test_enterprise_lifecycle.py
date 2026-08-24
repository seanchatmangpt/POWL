import threading

import pytest

from powl.enterprise import (
    ADMPhase,
    ActuationAuthorization,
    ArchitectureAdmissionError,
    ArchitectureContract,
    ArchitectureLayer,
    ArchitectureRepository,
    ArchitectureState,
    BuildingBlock,
    BuildingBlockKind,
    WorkPackage,
    architecture_plan_fingerprint,
    architecture_state_fingerprint,
    architecture_to_turtle,
    authorize_architecture_plan,
    compare_architecture_states,
    compile_drift_remediation,
    compile_togaf_plan,
    compile_transition_architecture,
    detect_architecture_drift,
    execute_architecture_plan,
)


def _abb(block_id, name, layer, *, capabilities=(), controls=()):
    return BuildingBlock(
        id=block_id,
        name=name,
        layer=layer,
        kind=BuildingBlockKind.ABB,
        capabilities=frozenset(capabilities),
        controls=frozenset(controls),
    )


def _sbb(
    block_id,
    name,
    layer,
    *,
    version="1",
    realizes=(),
    depends_on=(),
    capabilities=(),
    controls=(),
):
    return BuildingBlock(
        id=block_id,
        name=name,
        layer=layer,
        kind=BuildingBlockKind.SBB,
        version=version,
        realizes=frozenset(realizes),
        depends_on=frozenset(depends_on),
        capabilities=frozenset(capabilities),
        controls=frozenset(controls),
    )


def test_architecture_repository_tracks_abb_sbb_realization_and_lineage():
    baseline = ArchitectureState(
        "baseline",
        (
            _abb(
                "customer-api",
                "Customer API",
                ArchitectureLayer.APPLICATION,
                capabilities=("customer-access",),
            ),
            _sbb(
                "api-v1",
                "Customer API v1",
                ArchitectureLayer.APPLICATION,
                realizes=("customer-api",),
                capabilities=("customer-access",),
            ),
        ),
        controls=frozenset(("architecture-approved",)),
    )
    target = ArchitectureState(
        "target",
        (
            _abb(
                "customer-api",
                "Customer API",
                ArchitectureLayer.APPLICATION,
                capabilities=("customer-access",),
            ),
            _abb(
                "observability",
                "Observability",
                ArchitectureLayer.TECHNOLOGY,
                capabilities=("runtime-observability",),
            ),
            _sbb(
                "api-v1",
                "Customer API v1",
                ArchitectureLayer.APPLICATION,
                version="2",
                realizes=("customer-api",),
                capabilities=("customer-access",),
            ),
            _sbb(
                "otel",
                "OpenTelemetry Platform",
                ArchitectureLayer.TECHNOLOGY,
                realizes=("observability",),
                depends_on=("api-v1",),
                capabilities=("runtime-observability",),
            ),
        ),
        controls=frozenset(("architecture-approved", "operational-readiness")),
    )

    assert baseline.realization_coverage == 1.0
    assert target.realization_coverage == 1.0
    assert target.unrealized_abbs == ()

    repo = ArchitectureRepository()
    first = repo.commit(baseline)
    second = repo.commit(target, parent_id=baseline.id)

    assert first.fingerprint == architecture_state_fingerprint(baseline)
    assert second.fingerprint == architecture_state_fingerprint(target)
    assert [revision.state.id for revision in repo.history(target.id)] == [
        "baseline",
        "target",
    ]

    with pytest.raises(ArchitectureAdmissionError) as duplicate:
        repo.commit(target)
    assert duplicate.value.code == "DUPLICATE_ARCHITECTURE_STATE"


def test_transition_architecture_generates_only_delta_work_and_parallelizes_it():
    baseline = ArchitectureState(
        "baseline",
        (
            _abb("runtime", "Runtime", ArchitectureLayer.TECHNOLOGY),
            _abb("telemetry", "Telemetry", ArchitectureLayer.TECHNOLOGY),
            _sbb(
                "runtime-sbb",
                "Runtime Platform",
                ArchitectureLayer.TECHNOLOGY,
                version="1",
                realizes=("runtime",),
                controls=("architecture-approved",),
            ),
            _sbb(
                "legacy",
                "Legacy Monitor",
                ArchitectureLayer.TECHNOLOGY,
                controls=("architecture-approved",),
            ),
        ),
    )
    target = ArchitectureState(
        "target",
        (
            _abb("runtime", "Runtime", ArchitectureLayer.TECHNOLOGY),
            _abb("telemetry", "Telemetry", ArchitectureLayer.TECHNOLOGY),
            _sbb(
                "runtime-sbb",
                "Runtime Platform",
                ArchitectureLayer.TECHNOLOGY,
                version="2",
                realizes=("runtime",),
                controls=("architecture-approved",),
            ),
            _sbb(
                "otel",
                "OpenTelemetry",
                ArchitectureLayer.TECHNOLOGY,
                realizes=("telemetry",),
                depends_on=("runtime-sbb",),
                controls=("architecture-approved",),
            ),
        ),
    )
    contract = ArchitectureContract(
        name="enterprise",
        required_controls=frozenset(("architecture-approved",)),
    )

    transition = compile_transition_architecture(
        baseline,
        target,
        contract=contract,
    )

    assert [block.id for block in transition.delta.added] == ["otel"]
    assert [block.id for block in transition.delta.removed] == ["legacy"]
    assert [(before.id, after.id) for before, after in transition.delta.changed] == [
        ("runtime-sbb", "runtime-sbb")
    ]
    assert {package.id for package in transition.plan.work_packages} == {
        "change:runtime-sbb",
        "deploy:otel",
        "retire:legacy",
    }
    assert transition.plan.initial_frontier == (
        "change:runtime-sbb",
        "retire:legacy",
    )
    assert transition.concurrency_width == 2
    assert transition.critical_path_length == 2
    assert transition.plan.ready_work_packages(
        {"change:runtime-sbb"}
    ) == ("deploy:otel", "retire:legacy")


def test_phase_h_drift_detection_compiles_back_to_a_remediation_plan():
    target = ArchitectureState(
        "target",
        (
            _abb("runtime", "Runtime", ArchitectureLayer.TECHNOLOGY),
            _sbb(
                "runtime-sbb",
                "Runtime Platform",
                ArchitectureLayer.TECHNOLOGY,
                version="2",
                realizes=("runtime",),
                controls=("architecture-approved",),
            ),
        ),
        controls=frozenset(("architecture-approved", "operational-readiness")),
    )
    observed = ArchitectureState(
        "observed",
        (
            _abb("runtime", "Runtime", ArchitectureLayer.TECHNOLOGY),
            _sbb(
                "runtime-sbb",
                "Runtime Platform",
                ArchitectureLayer.TECHNOLOGY,
                version="1",
                realizes=("runtime",),
                controls=("architecture-approved",),
            ),
            _sbb(
                "shadow",
                "Unapproved Shadow Runtime",
                ArchitectureLayer.TECHNOLOGY,
            ),
        ),
        controls=frozenset(("architecture-approved",)),
    )

    report = detect_architecture_drift(target, observed)
    assert not report.is_conformant
    assert {(finding.kind.value, finding.subject_id) for finding in report.findings} == {
        ("block-changed", "runtime-sbb"),
        ("unexpected-block", "shadow"),
        ("state-control-missing", "operational-readiness"),
    }

    remediation = compile_drift_remediation(target, observed)
    assert {package.id for package in remediation.plan.work_packages} == {
        "change:runtime-sbb",
        "retire:shadow",
    }


def test_deterministic_rdf_projection_uses_public_provenance_and_metadata_vocabularies():
    a = ArchitectureState(
        "target state",
        (
            _sbb(
                "runtime/sbb",
                "Runtime",
                ArchitectureLayer.TECHNOLOGY,
                realizes=("runtime-abb",),
                controls=("zero-unreceipted-actuation",),
            ),
            _abb(
                "runtime-abb",
                "Runtime Architecture",
                ArchitectureLayer.TECHNOLOGY,
                capabilities=("execute-work",),
            ),
        ),
        controls=frozenset(("architecture-approved",)),
    )
    b = ArchitectureState(
        "target state",
        tuple(reversed(a.building_blocks)),
        controls=a.controls,
    )

    ttl_a = architecture_to_turtle(a)
    ttl_b = architecture_to_turtle(b)

    assert ttl_a == ttl_b
    assert "@prefix prov: <http://www.w3.org/ns/prov#> ." in ttl_a
    assert "@prefix dcterms: <http://purl.org/dc/terms/> ." in ttl_a
    assert "@prefix skos: <http://www.w3.org/2004/02/skos/core#> ." in ttl_a
    assert "arch:ArchitectureBuildingBlock" in ttl_a
    assert "arch:SolutionBuildingBlock" in ttl_a
    assert "urn:powl:architecture:block:runtime%2Fsbb" in ttl_a
    assert architecture_state_fingerprint(a) == architecture_state_fingerprint(b)


def test_bounded_actuation_requires_exact_plan_identity_and_scope():
    plan = compile_togaf_plan(
        (
            WorkPackage("business", "Business", ADMPhase.B),
            WorkPackage("data", "Data", ADMPhase.C),
            WorkPackage(
                "solutions",
                "Solutions",
                ADMPhase.E,
                depends_on=frozenset(("business", "data")),
            ),
        )
    )

    authorization = authorize_architecture_plan(plan)
    assert authorization.plan_fingerprint == architecture_plan_fingerprint(plan)

    with pytest.raises(ArchitectureAdmissionError) as bad_fingerprint:
        execute_architecture_plan(
            plan,
            lambda package: package.id,
            authorization=ActuationAuthorization(
                plan_fingerprint="not-the-plan",
                admitted_work_package_ids=authorization.admitted_work_package_ids,
            ),
        )
    assert bad_fingerprint.value.code == "PLAN_FINGERPRINT_MISMATCH"

    with pytest.raises(ArchitectureAdmissionError) as bad_scope:
        execute_architecture_plan(
            plan,
            lambda package: package.id,
            authorization=ActuationAuthorization(
                plan_fingerprint=authorization.plan_fingerprint,
                admitted_work_package_ids=frozenset(("business", "data")),
            ),
        )
    assert bad_scope.value.code == "ACTUATION_SCOPE_MISMATCH"

    frontier = {"business", "data"}
    barrier = threading.Barrier(2, timeout=5)
    completed = set()
    lock = threading.Lock()

    def actuator(package):
        if package.id in frontier:
            barrier.wait()
            with lock:
                completed.add(package.id)
            return package.id
        with lock:
            assert completed == frontier
        return package.id

    receipt = execute_architecture_plan(
        plan,
        actuator,
        authorization=authorization,
        max_workers=2,
    )

    assert {execution.result for execution in receipt.executions} == {
        "business",
        "data",
        "solutions",
    }


def test_invalid_realization_and_dependency_models_are_refused():
    with pytest.raises(ArchitectureAdmissionError) as missing:
        ArchitectureState(
            "bad",
            (
                _sbb(
                    "runtime",
                    "Runtime",
                    ArchitectureLayer.TECHNOLOGY,
                    realizes=("missing-abb",),
                ),
            ),
        )
    assert missing.value.code == "UNKNOWN_REALIZATION_TARGET"

    with pytest.raises(ArchitectureAdmissionError) as cycle:
        ArchitectureState(
            "cycle",
            (
                _sbb(
                    "a",
                    "A",
                    ArchitectureLayer.APPLICATION,
                    depends_on=("b",),
                ),
                _sbb(
                    "b",
                    "B",
                    ArchitectureLayer.APPLICATION,
                    depends_on=("a",),
                ),
            ),
        )
    assert cycle.value.code == "CYCLIC_BUILDING_BLOCK_DEPENDENCY"


def test_compare_architecture_states_detects_state_level_capability_and_control_delta():
    baseline = ArchitectureState(
        "baseline",
        (
            _sbb(
                "service",
                "Service",
                ArchitectureLayer.APPLICATION,
                capabilities=("old-capability",),
            ),
        ),
        controls=frozenset(("old-control",)),
    )
    target = ArchitectureState(
        "target",
        (
            _sbb(
                "service",
                "Service",
                ArchitectureLayer.APPLICATION,
                version="2",
                capabilities=("new-capability",),
            ),
        ),
        controls=frozenset(("new-control",)),
    )

    delta = compare_architecture_states(baseline, target)
    assert delta.capabilities_added == frozenset(("new-capability",))
    assert delta.capabilities_removed == frozenset(("old-capability",))
    assert delta.controls_added == frozenset(("new-control",))
    assert delta.controls_removed == frozenset(("old-control",))

from datetime import datetime, timezone

import pytest

from powl.enterprise import (
    ADMPhase,
    ArchitectureAdmissionError,
    ArchitectureLayer,
    ArchitectureState,
    BuildingBlock,
    BuildingBlockKind,
    GymActBinding,
    WorkPackage,
    compile_autofde_pddl,
    compile_ecosystem_handoff,
    compile_ggen_manufacturing_bundle,
    compile_gymact_projection,
    compile_togaf_plan,
    ecosystem_contract_manifest,
    project_execution_to_ocel,
    validate_autofde_candidate,
)
from powl.execution import SpiffPOWLExecutor


def _state():
    return ArchitectureState(
        id="target-v1",
        building_blocks=(
            BuildingBlock(
                id="abb-runtime",
                name="Enterprise Runtime",
                layer=ArchitectureLayer.TECHNOLOGY,
                kind=BuildingBlockKind.ABB,
                capabilities=frozenset(("runtime",)),
            ),
            BuildingBlock(
                id="sbb-kubernetes",
                name="Kubernetes Runtime",
                layer=ArchitectureLayer.TECHNOLOGY,
                kind=BuildingBlockKind.SBB,
                realizes=frozenset(("abb-runtime",)),
                capabilities=frozenset(("runtime",)),
                controls=frozenset(("architecture-approved",)),
            ),
        ),
        controls=frozenset(("architecture-approved",)),
    )


def _plan():
    return compile_togaf_plan(
        (
            WorkPackage(
                id="business",
                name="Business Architecture",
                phase=ADMPhase.B,
                controls=frozenset(("architecture-approved",)),
            ),
            WorkPackage(
                id="data",
                name="Data Architecture",
                phase=ADMPhase.C,
                controls=frozenset(("architecture-approved",)),
            ),
            WorkPackage(
                id="runtime",
                name="Runtime Architecture",
                phase=ADMPhase.D,
                controls=frozenset(("architecture-approved",)),
            ),
            WorkPackage(
                id="solutions",
                name="Opportunities and Solutions",
                phase=ADMPhase.E,
                depends_on=frozenset(("business", "data", "runtime")),
                controls=frozenset(("architecture-approved",)),
            ),
        )
    )


def _bindings(plan):
    return tuple(
        GymActBinding(
            work_package_id=package.id,
            episode_id="episode-enterprise",
            capability=f"urn:gymact:capability:{package.id}",
            authority_ref="urn:authority:brce",
            principal="urn:principal:powl",
            payload={"target": package.id},
        )
        for package in plan.work_packages
    )


def test_ggen_bundle_is_deterministic_executable_shape():
    state = _state()

    first = compile_ggen_manufacturing_bundle(state)
    second = compile_ggen_manufacturing_bundle(state)

    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.command == ("ggen", "sync", "run")
    assert set(first.file_map) == {
        "ggen.toml",
        "ontology/architecture.ttl",
        "ontology/architecture.shacl.ttl",
        "queries/architecture-blocks.rq",
        "templates/architecture-index.md.tera",
    }
    manifest = first.file_map["ggen.toml"]
    assert "[[generation.rules]]" in manifest
    assert 'shacl = ["ontology/architecture.shacl.ttl"]' in manifest
    assert "strict_mode = true" in manifest
    assert "ORDER BY ?id" in first.file_map["queries/architecture-blocks.rq"]
    assert "prov:Collection" in first.file_map["ontology/architecture.ttl"]


def test_gymact_projection_matches_actuation_intent_and_requires_exact_binding():
    plan = _plan()
    projection = compile_gymact_projection(plan, _bindings(plan))

    assert projection.requires_brce
    assert len(projection.intents) == len(plan.work_packages)
    first = projection.intents[0].intent
    assert set(first) == {
        "episode_id",
        "capability",
        "payload",
        "authority_ref",
        "principal",
        "idempotency_key",
        "operation",
    }
    assert first["operation"] == "act"
    assert first["authority_ref"] == "urn:authority:brce"
    assert first["payload"]["powl"]["plan_fingerprint"] == projection.plan_fingerprint

    with pytest.raises(ArchitectureAdmissionError) as exc:
        compile_gymact_projection(plan, _bindings(plan)[:-1])
    assert exc.value.code == "MISSING_GYMACT_BINDING"


def test_autofde_projection_is_planner_advisory_and_revalidated_against_powl():
    plan = _plan()
    projection = compile_autofde_pddl(plan)

    assert ":requirements :strips" in projection.domain_pddl
    assert "(:goal" in projection.problem_pddl
    action_for = {package_id: action for action, package_id in projection.action_to_work_package}

    candidate = (
        action_for["runtime"],
        action_for["business"],
        action_for["data"],
        action_for["solutions"],
    )
    assert validate_autofde_candidate(plan, projection, candidate) == (
        "runtime",
        "business",
        "data",
        "solutions",
    )

    with pytest.raises(ArchitectureAdmissionError) as exc:
        validate_autofde_candidate(
            plan,
            projection,
            (action_for["solutions"], action_for["business"], action_for["data"], action_for["runtime"]),
        )
    assert exc.value.code == "AUTOFDE_PRECEDENCE_VIOLATION"


def test_execution_projects_to_wasm4pm_compat_ocel_shape():
    plan = _plan()
    receipt = SpiffPOWLExecutor(max_workers=4).execute(
        plan.model,
        lambda activity: activity.get_attribute("architecture.work_package_id"),
    )

    evidence = project_execution_to_ocel(
        plan,
        receipt,
        run_started_at=datetime(2026, 8, 14, 23, 0, tzinfo=timezone.utc),
    )

    ocel = evidence.ocel
    assert set(ocel) == {"eventTypes", "objectTypes", "events", "objects"}
    assert len(ocel["events"]) == 4
    assert len(ocel["objects"]) == 5
    assert {item["name"] for item in ocel["objectTypes"]} == {
        "ArchitecturePlan",
        "WorkPackage",
    }
    assert all(
        relationship["qualifier"]
        for event in ocel["events"]
        for relationship in event["relationships"]
    )
    assert evidence.graduation_candidate == {
        "reason": "NeedsConformanceExecution",
        "subject": f"architecture-plan:{evidence.plan_fingerprint}",
        "evidence_hash": evidence.fingerprint,
        "target": "wasm4pm",
        "witness": "Ocel20",
    }


def test_process_evidence_refuses_naive_wall_clock_anchor():
    plan = _plan()
    receipt = SpiffPOWLExecutor(max_workers=4).execute(plan.model, lambda activity: activity.label)

    with pytest.raises(ArchitectureAdmissionError) as exc:
        project_execution_to_ocel(
            plan,
            receipt,
            run_started_at=datetime(2026, 8, 14, 23, 0),
        )
    assert exc.value.code == "NAIVE_PROCESS_EVIDENCE_TIME"


def test_full_ecosystem_handoff_is_one_fingerprinted_contract():
    state = _state()
    plan = _plan()

    handoff = compile_ecosystem_handoff(state, plan, _bindings(plan))
    repeated = compile_ecosystem_handoff(state, plan, _bindings(plan))

    assert handoff == repeated
    assert handoff.fingerprint == repeated.fingerprint
    assert handoff.state_fingerprint == handoff.ggen.state_fingerprint
    assert handoff.plan_fingerprint == handoff.gymact.plan_fingerprint
    assert handoff.plan_fingerprint == handoff.autofde.plan_fingerprint


def test_ecosystem_authority_manifest_has_no_role_collapse():
    manifest = ecosystem_contract_manifest()
    projects = {project["project"] for project in manifest["projects"]}

    assert projects == {
        "ggen",
        "gymact",
        "autofde-lab",
        "wasm4pm-compat",
        "wasm4pm",
        "process-intelligence",
    }
    law = manifest["law"]
    assert law["control_flow_authority"] == "POWL"
    assert law["manufacturer"] == "ggen"
    assert law["do_boundary"] == "GymAct/BRCE"
    assert law["planner"] == "autofde-lab"
    assert law["evidence_boundary"] == "wasm4pm-compat"
    assert law["process_intelligence_executor"] == "wasm4pm"

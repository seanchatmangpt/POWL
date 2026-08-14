from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple

from powl.execution import ExecutionReceipt

from .lifecycle import (
    ArchitectureState,
    architecture_plan_fingerprint,
    architecture_state_fingerprint,
    architecture_to_turtle,
)
from .togaf import ArchitectureAdmissionError, ArchitecturePlan, WorkPackage


class EcosystemProject(str, Enum):
    GGEN = "ggen"
    GYMACT = "gymact"
    AUTOFDE_LAB = "autofde-lab"
    WASM4PM_COMPAT = "wasm4pm-compat"
    WASM4PM = "wasm4pm"
    PROCESS_INTELLIGENCE = "process-intelligence"


@dataclass(frozen=True)
class EcosystemProjectContract:
    project: EcosystemProject
    repository: str
    role: str
    consumes: Tuple[str, ...]
    produces: Tuple[str, ...]
    authority: str


ECOSYSTEM_CONTRACTS: Tuple[EcosystemProjectContract, ...] = (
    EcosystemProjectContract(
        project=EcosystemProject.GGEN,
        repository="seanchatmangpt/ggen",
        role="deterministic graph-backed manufacture",
        consumes=("admitted RDF", "templates", "policy"),
        produces=("artifacts", "generation receipts"),
        authority="manufacture",
    ),
    EcosystemProjectContract(
        project=EcosystemProject.GYMACT,
        repository="seanchatmangpt/gymact",
        role="bounded consequential execution and evidence",
        consumes=("ActuationIntent", "authority decision"),
        produces=("verified transition", "receipt ledger"),
        authority="DO through BRCE",
    ),
    EcosystemProjectContract(
        project=EcosystemProject.AUTOFDE_LAB,
        repository="seanchatmangpt/autofde-lab",
        role="planner and solver exploration",
        consumes=("planning problem",),
        produces=("candidate plan",),
        authority="advisory planning only",
    ),
    EcosystemProjectContract(
        project=EcosystemProject.WASM4PM_COMPAT,
        repository="seanchatmangpt/wasm4pm-compat",
        role="process-evidence type-law boundary",
        consumes=("OCEL 2.0 evidence",),
        produces=("admission/refusal", "graduation candidate"),
        authority="structural evidence",
    ),
    EcosystemProjectContract(
        project=EcosystemProject.WASM4PM,
        repository="seanchatmangpt/wasm4pm",
        role="process-intelligence execution",
        consumes=("graduated process evidence",),
        produces=("discovery", "conformance", "replay", "receipts"),
        authority="process-intelligence execution",
    ),
    EcosystemProjectContract(
        project=EcosystemProject.PROCESS_INTELLIGENCE,
        repository="seanchatmangpt/process-intelligence",
        role="research and lifecycle authority for process intelligence",
        consumes=("process evidence", "analysis evidence"),
        produces=("research verdicts", "downstream authorizations"),
        authority="research",
    ),
)


@dataclass(frozen=True)
class GgenManufacturingBundle:
    state_id: str
    state_fingerprint: str
    files: Tuple[Tuple[str, str], ...]
    command: Tuple[str, ...] = ("ggen", "sync", "run")

    @property
    def file_map(self) -> Mapping[str, str]:
        return dict(self.files)

    @property
    def fingerprint(self) -> str:
        payload = {
            "state_id": self.state_id,
            "state_fingerprint": self.state_fingerprint,
            "command": list(self.command),
            "files": list(self.files),
        }
        return _sha256_json(payload)


@dataclass(frozen=True)
class GymActBinding:
    work_package_id: str
    episode_id: str
    capability: str
    authority_ref: str
    principal: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GymActIntentProjection:
    work_package_id: str
    intent: Mapping[str, Any]


@dataclass(frozen=True)
class GymActExecutionProjection:
    plan_fingerprint: str
    intents: Tuple[GymActIntentProjection, ...]
    requires_brce: bool = True

    @property
    def fingerprint(self) -> str:
        return _sha256_json(
            {
                "plan_fingerprint": self.plan_fingerprint,
                "requires_brce": self.requires_brce,
                "intents": [
                    {
                        "work_package_id": item.work_package_id,
                        "intent": item.intent,
                    }
                    for item in self.intents
                ],
            }
        )


@dataclass(frozen=True)
class AutoFDEPddlProjection:
    plan_fingerprint: str
    domain_name: str
    problem_name: str
    domain_pddl: str
    problem_pddl: str
    action_to_work_package: Tuple[Tuple[str, str], ...]

    @property
    def action_map(self) -> Mapping[str, str]:
        return dict(self.action_to_work_package)

    @property
    def fingerprint(self) -> str:
        return _sha256_json(
            {
                "plan_fingerprint": self.plan_fingerprint,
                "domain_pddl": self.domain_pddl,
                "problem_pddl": self.problem_pddl,
                "action_to_work_package": list(self.action_to_work_package),
            }
        )


@dataclass(frozen=True)
class ProcessEvidenceProjection:
    plan_fingerprint: str
    ocel: Mapping[str, Any]
    graduation_candidate: Mapping[str, str]

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.ocel,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EcosystemHandoff:
    state_fingerprint: str
    plan_fingerprint: str
    ggen: GgenManufacturingBundle
    gymact: GymActExecutionProjection
    autofde: AutoFDEPddlProjection

    @property
    def fingerprint(self) -> str:
        return _sha256_json(
            {
                "state_fingerprint": self.state_fingerprint,
                "plan_fingerprint": self.plan_fingerprint,
                "ggen": self.ggen.fingerprint,
                "gymact": self.gymact.fingerprint,
                "autofde": self.autofde.fingerprint,
            }
        )


def compile_ggen_manufacturing_bundle(state: ArchitectureState) -> GgenManufacturingBundle:
    state_fp = architecture_state_fingerprint(state)
    safe_name = _slug(state.id)
    ontology = architecture_to_turtle(state)
    shapes = """@prefix arch: <urn:powl:architecture:> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

arch:BuildingBlockShape a sh:NodeShape ;
    sh:targetClass arch:ArchitectureBuildingBlock ;
    sh:targetClass arch:SolutionBuildingBlock ;
    sh:property [ sh:path dcterms:identifier ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path skos:prefLabel ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path arch:layer ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path arch:version ; sh:minCount 1 ; sh:maxCount 1 ] .
"""
    query = """PREFIX arch: <urn:powl:architecture:>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT ?id ?label ?layer ?version ?kind
WHERE {
  ?block a ?kind ;
         dcterms:identifier ?id ;
         skos:prefLabel ?label ;
         arch:layer ?layer ;
         arch:version ?version .
  VALUES ?kind { arch:ArchitectureBuildingBlock arch:SolutionBuildingBlock }
}
ORDER BY ?id
"""
    template = """# Architecture Index

State: {{ state_id | default(value=\"unknown\") }}

| ID | Name | Layer | Version | Kind |
|---|---|---|---|---|
{% for row in sparql_results -%}
| {{ row[\"id\"] | default(value=\"\") }} | {{ row[\"label\"] | default(value=\"\") }} | {{ row[\"layer\"] | default(value=\"\") }} | {{ row[\"version\"] | default(value=\"\") }} | {{ row[\"kind\"] | default(value=\"\") }} |
{% endfor -%}
"""
    manifest = f"""[project]
name = \"powl-architecture-{safe_name}\"
version = \"0.1.0\"
description = \"POWL enterprise architecture manufacturing projection for {state.id}\"
authors = [\"POWL ecosystem bridge\"]
license = \"MIT\"

[ontology]
source = \"ontology/architecture.ttl\"
base_iri = \"urn:powl:architecture:\"

[ontology.prefixes]
arch = \"urn:powl:architecture:\"
dcterms = \"http://purl.org/dc/terms/\"
prov = \"http://www.w3.org/ns/prov#\"
skos = \"http://www.w3.org/2004/02/skos/core#\"

[generation]
output_dir = \"generated/\"

[[generation.rules]]
name = \"architecture-index\"
query = {{ file = \"queries/architecture-blocks.rq\" }}
template = {{ file = \"templates/architecture-index.md.tera\" }}
output_file = \"ARCHITECTURE_INDEX.md\"
mode = \"Overwrite\"

[validation]
shacl = [\"ontology/architecture.shacl.ttl\"]
strict_mode = true

[sync]
enabled = true
on_change = \"manual\"
validate_after = true
conflict_mode = \"fail\"

[rdf]
formats = [\"turtle\"]
default_format = \"turtle\"
strict_validation = false

[templates]
enable_caching = true
auto_reload = true

[output]
formatting = \"default\"
line_length = 100
indent = 2
"""
    files = (
        ("ggen.toml", manifest),
        ("ontology/architecture.ttl", ontology),
        ("ontology/architecture.shacl.ttl", shapes),
        ("queries/architecture-blocks.rq", query),
        ("templates/architecture-index.md.tera", template),
    )
    return GgenManufacturingBundle(
        state_id=state.id,
        state_fingerprint=state_fp,
        files=files,
    )


def compile_gymact_projection(
    plan: ArchitecturePlan,
    bindings: Sequence[GymActBinding],
) -> GymActExecutionProjection:
    plan_fp = architecture_plan_fingerprint(plan)
    package_by_id = {package.id: package for package in plan.work_packages}
    binding_by_id: Dict[str, GymActBinding] = {}

    for binding in bindings:
        if binding.work_package_id in binding_by_id:
            raise ArchitectureAdmissionError(
                "DUPLICATE_GYMACT_BINDING",
                f"Duplicate GymAct binding for {binding.work_package_id}",
                work_package_id=binding.work_package_id,
            )
        if binding.work_package_id not in package_by_id:
            raise ArchitectureAdmissionError(
                "UNKNOWN_GYMACT_WORK_PACKAGE",
                f"GymAct binding refers to unknown work package: {binding.work_package_id}",
                work_package_id=binding.work_package_id,
            )
        if not binding.episode_id or not binding.capability or not binding.authority_ref:
            raise ArchitectureAdmissionError(
                "INCOMPLETE_GYMACT_BINDING",
                "GymAct consequential execution requires episode, capability, and authority reference.",
                work_package_id=binding.work_package_id,
            )
        binding_by_id[binding.work_package_id] = binding

    missing = sorted(set(package_by_id).difference(binding_by_id))
    if missing:
        raise ArchitectureAdmissionError(
            "MISSING_GYMACT_BINDING",
            "Every admitted work package requires an explicit GymAct binding: "
            + ", ".join(missing),
        )

    projections = []
    for package in sorted(plan.work_packages, key=lambda item: item.id):
        binding = binding_by_id[package.id]
        payload = {
            "powl": {
                "plan_fingerprint": plan_fp,
                "work_package_id": package.id,
                "name": package.name,
                "adm_phase": package.phase.value,
                "depends_on": sorted(package.depends_on),
                "controls": sorted(package.controls),
            },
            "input": dict(binding.payload),
        }
        idempotency_key = hashlib.sha256(
            f"{plan_fp}:{package.id}:{binding.episode_id}:{binding.capability}".encode("utf-8")
        ).hexdigest()
        intent = {
            "episode_id": binding.episode_id,
            "capability": binding.capability,
            "payload": payload,
            "authority_ref": binding.authority_ref,
            "principal": binding.principal,
            "idempotency_key": idempotency_key,
            "operation": "act",
        }
        projections.append(
            GymActIntentProjection(
                work_package_id=package.id,
                intent=intent,
            )
        )

    return GymActExecutionProjection(
        plan_fingerprint=plan_fp,
        intents=tuple(projections),
        requires_brce=True,
    )


def compile_autofde_pddl(plan: ArchitecturePlan) -> AutoFDEPddlProjection:
    plan_fp = architecture_plan_fingerprint(plan)
    packages = sorted(plan.work_packages, key=lambda item: item.id)
    package_ids = {package.id for package in packages}

    action_names: Dict[str, str] = {}
    used_names = set()
    for package in packages:
        base = "do-" + _pddl_identifier(package.id)
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        used_names.add(name)
        action_names[package.id] = name

    predicate_names = {
        package.id: "done-" + _pddl_identifier(package.id)
        for package in packages
    }

    domain_name = "powl-enterprise-" + plan_fp[:12]
    problem_name = "execute-" + plan_fp[:12]
    lines = [
        f"(define (domain {domain_name})",
        "  (:requirements :strips)",
        "  (:predicates",
    ]
    for package in packages:
        lines.append(f"    ({predicate_names[package.id]})")
    lines.append("  )")

    for package in packages:
        unknown = set(package.depends_on).difference(package_ids)
        if unknown:
            raise ArchitectureAdmissionError(
                "AUTOFDE_UNKNOWN_DEPENDENCY",
                "AutoFDE projection encountered an unknown admitted dependency: "
                + ", ".join(sorted(unknown)),
                work_package_id=package.id,
            )
        dependencies = [predicate_names[item] for item in sorted(package.depends_on)]
        precondition = "(and)" if not dependencies else "(and " + " ".join(
            f"({item})" for item in dependencies
        ) + ")"
        lines.extend(
            [
                f"  (:action {action_names[package.id]}",
                f"    :precondition {precondition}",
                f"    :effect ({predicate_names[package.id]})",
                "  )",
            ]
        )
    lines.append(")")
    domain_pddl = "\n".join(lines) + "\n"

    goal = "(and " + " ".join(
        f"({predicate_names[package.id]})" for package in packages
    ) + ")"
    problem_pddl = "\n".join(
        [
            f"(define (problem {problem_name})",
            f"  (:domain {domain_name})",
            "  (:init)",
            f"  (:goal {goal})",
            ")",
            "",
        ]
    )

    return AutoFDEPddlProjection(
        plan_fingerprint=plan_fp,
        domain_name=domain_name,
        problem_name=problem_name,
        domain_pddl=domain_pddl,
        problem_pddl=problem_pddl,
        action_to_work_package=tuple(
            sorted((action, package_id) for package_id, action in action_names.items())
        ),
    )


def validate_autofde_candidate(
    plan: ArchitecturePlan,
    projection: AutoFDEPddlProjection,
    action_sequence: Sequence[str],
) -> Tuple[str, ...]:
    expected_plan_fp = architecture_plan_fingerprint(plan)
    if projection.plan_fingerprint != expected_plan_fp:
        raise ArchitectureAdmissionError(
            "AUTOFDE_PLAN_FINGERPRINT_MISMATCH",
            "AutoFDE candidate was produced for a different architecture plan.",
        )

    action_map = projection.action_map
    package_by_id = {package.id: package for package in plan.work_packages}
    package_sequence = []
    seen = set()

    for action in action_sequence:
        if action not in action_map:
            raise ArchitectureAdmissionError(
                "AUTOFDE_UNKNOWN_ACTION",
                f"AutoFDE candidate contains unknown action: {action}",
            )
        package_id = action_map[action]
        if package_id in seen:
            raise ArchitectureAdmissionError(
                "AUTOFDE_DUPLICATE_ACTION",
                f"AutoFDE candidate repeats work package: {package_id}",
                work_package_id=package_id,
            )
        package = package_by_id[package_id]
        unmet = set(package.depends_on).difference(seen)
        if unmet:
            raise ArchitectureAdmissionError(
                "AUTOFDE_PRECEDENCE_VIOLATION",
                f"AutoFDE candidate schedules {package_id} before dependencies: "
                + ", ".join(sorted(unmet)),
                work_package_id=package_id,
            )
        seen.add(package_id)
        package_sequence.append(package_id)

    missing = sorted(set(package_by_id).difference(seen))
    if missing:
        raise ArchitectureAdmissionError(
            "AUTOFDE_INCOMPLETE_PLAN",
            "AutoFDE candidate omits admitted work packages: " + ", ".join(missing),
        )

    return tuple(package_sequence)


def project_execution_to_ocel(
    plan: ArchitecturePlan,
    receipt: ExecutionReceipt,
    *,
    run_started_at: datetime,
) -> ProcessEvidenceProjection:
    if run_started_at.tzinfo is None or run_started_at.utcoffset() is None:
        raise ArchitectureAdmissionError(
            "NAIVE_PROCESS_EVIDENCE_TIME",
            "Process-evidence anchoring requires an offset-aware datetime.",
        )

    plan_fp = architecture_plan_fingerprint(plan)
    package_by_id = {package.id: package for package in plan.work_packages}
    activity_to_package = {
        id(activity): package_id for package_id, activity in plan.activities.items()
    }

    observed_package_ids = []
    for execution in receipt.executions:
        package_id = activity_to_package.get(id(execution.activity))
        if package_id is None:
            package_id = execution.activity.get_attribute("architecture.work_package_id")
        if package_id not in package_by_id:
            raise ArchitectureAdmissionError(
                "UNBOUND_PROCESS_EVIDENCE_ACTIVITY",
                f"Execution receipt contains an activity outside the admitted architecture plan: {package_id}",
            )
        observed_package_ids.append(package_id)

    if len(observed_package_ids) != len(set(observed_package_ids)):
        raise ArchitectureAdmissionError(
            "DUPLICATE_PROCESS_EVIDENCE_ACTIVITY",
            "Exact-once architecture execution produced duplicate work-package evidence.",
        )
    missing = sorted(set(package_by_id).difference(observed_package_ids))
    if missing:
        raise ArchitectureAdmissionError(
            "INCOMPLETE_PROCESS_EVIDENCE",
            "Execution receipt omits admitted work packages: " + ", ".join(missing),
        )

    baseline_ns = min(
        (execution.started_ns for execution in receipt.executions),
        default=0,
    )
    anchor = run_started_at.astimezone(timezone.utc)

    event_types = [
        {
            "name": "architecture-work-package-executed",
            "attributes": [
                {"name": "startedNs", "type": "integer"},
                {"name": "finishedNs", "type": "integer"},
                {"name": "durationNs", "type": "integer"},
                {"name": "threadId", "type": "integer"},
                {"name": "admPhase", "type": "string"},
                {"name": "result", "type": "string"},
            ],
        }
    ]
    object_types = [
        {
            "name": "ArchitecturePlan",
            "attributes": [
                {"name": "fingerprint", "type": "string"},
            ],
        },
        {
            "name": "WorkPackage",
            "attributes": [
                {"name": "name", "type": "string"},
                {"name": "admPhase", "type": "string"},
            ],
        },
    ]

    objects = [
        {
            "id": f"plan:{plan_fp}",
            "type": "ArchitecturePlan",
            "attributes": [
                {
                    "name": "fingerprint",
                    "value": plan_fp,
                    "time": anchor.isoformat(),
                }
            ],
            "relationships": [],
        }
    ]
    for package in sorted(plan.work_packages, key=lambda item: item.id):
        objects.append(
            {
                "id": f"work-package:{package.id}",
                "type": "WorkPackage",
                "attributes": [
                    {"name": "name", "value": package.name, "time": anchor.isoformat()},
                    {"name": "admPhase", "value": package.phase.value, "time": anchor.isoformat()},
                ],
                "relationships": [
                    {
                        "objectId": f"work-package:{dependency}",
                        "qualifier": "depends-on",
                    }
                    for dependency in sorted(package.depends_on)
                ],
            }
        )

    events = []
    for index, execution in enumerate(
        sorted(receipt.executions, key=lambda item: (item.started_ns, item.finished_ns, item.thread_id))
    ):
        package_id = activity_to_package.get(id(execution.activity))
        if package_id is None:
            package_id = execution.activity.get_attribute("architecture.work_package_id")
        package = package_by_id[package_id]
        offset_ns = execution.started_ns - baseline_ns
        event_time = anchor + timedelta(microseconds=offset_ns / 1000)
        events.append(
            {
                "id": f"event:{index + 1}:{package_id}",
                "type": "architecture-work-package-executed",
                "time": event_time.isoformat(),
                "attributes": [
                    {"name": "startedNs", "value": execution.started_ns},
                    {"name": "finishedNs", "value": execution.finished_ns},
                    {"name": "durationNs", "value": execution.finished_ns - execution.started_ns},
                    {"name": "threadId", "value": execution.thread_id},
                    {"name": "admPhase", "value": package.phase.value},
                    {"name": "result", "value": str(execution.result)},
                ],
                "relationships": [
                    {
                        "objectId": f"work-package:{package_id}",
                        "qualifier": "executed-work-package",
                    },
                    {
                        "objectId": f"plan:{plan_fp}",
                        "qualifier": "execution-plan",
                    },
                ],
            }
        )

    ocel = {
        "eventTypes": event_types,
        "objectTypes": object_types,
        "events": events,
        "objects": objects,
    }
    evidence_hash = _sha256_json(ocel)
    graduation = {
        "reason": "NeedsConformanceExecution",
        "subject": f"architecture-plan:{plan_fp}",
        "evidence_hash": evidence_hash,
        "target": EcosystemProject.WASM4PM.value,
        "witness": "Ocel20",
    }
    return ProcessEvidenceProjection(
        plan_fingerprint=plan_fp,
        ocel=ocel,
        graduation_candidate=graduation,
    )


def compile_ecosystem_handoff(
    state: ArchitectureState,
    plan: ArchitecturePlan,
    gymact_bindings: Sequence[GymActBinding],
) -> EcosystemHandoff:
    return EcosystemHandoff(
        state_fingerprint=architecture_state_fingerprint(state),
        plan_fingerprint=architecture_plan_fingerprint(plan),
        ggen=compile_ggen_manufacturing_bundle(state),
        gymact=compile_gymact_projection(plan, gymact_bindings),
        autofde=compile_autofde_pddl(plan),
    )


def ecosystem_contract_manifest() -> Mapping[str, Any]:
    return {
        "projects": [
            {
                "project": contract.project.value,
                "repository": contract.repository,
                "role": contract.role,
                "consumes": list(contract.consumes),
                "produces": list(contract.produces),
                "authority": contract.authority,
            }
            for contract in ECOSYSTEM_CONTRACTS
        ],
        "law": {
            "planner": EcosystemProject.AUTOFDE_LAB.value,
            "control_flow_authority": "POWL",
            "manufacturer": EcosystemProject.GGEN.value,
            "do_boundary": "GymAct/BRCE",
            "evidence_boundary": EcosystemProject.WASM4PM_COMPAT.value,
            "process_intelligence_executor": EcosystemProject.WASM4PM.value,
            "research_authority": EcosystemProject.PROCESS_INTELLIGENCE.value,
        },
    }


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "state"


def _pddl_identifier(value: str) -> str:
    identifier = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    if not identifier:
        identifier = "work"
    if identifier[0].isdigit():
        identifier = "wp-" + identifier
    return identifier

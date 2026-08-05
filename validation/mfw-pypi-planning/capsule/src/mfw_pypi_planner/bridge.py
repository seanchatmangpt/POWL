from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence


class BridgeRefusal(RuntimeError):
    """A typed, lawful refusal at the planning projection boundary."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


_REGISTRATION_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)=(?P<module>[A-Za-z_][A-Za-z0-9_.]*):(?P<class_name>[A-Za-z_][A-Za-z0-9_]*)$"
)
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


@dataclass(frozen=True)
class EngineRegistration:
    name: str
    module: str
    class_name: str


def parse_registration(raw: str) -> EngineRegistration:
    match = _REGISTRATION_RE.fullmatch(raw)
    if match is None:
        raise BridgeRefusal(
            "invalid_engine_registration",
            "engine registration must be NAME=PYTHON.MODULE:CLASS with canonical identifiers",
        )
    return EngineRegistration(**match.groupdict())


def admit_plugins(
    factory: Any,
    *,
    registrations: Iterable[str] = (),
    load_modules: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Admit explicitly requested, already-installed UP plugins into one Factory."""
    loaded: list[str] = []
    registered: list[str] = []
    for module in load_modules:
        if _MODULE_RE.fullmatch(module) is None:
            raise BridgeRefusal(
                "invalid_plugin_module",
                f"plugin module {module!r} is not a canonical Python module name",
            )
        try:
            import_module(module)
        except ModuleNotFoundError as exc:
            raise BridgeRefusal(
                "plugin_missing", f"requested plugin module {module!r} is not installed"
            ) from exc
        loaded.append(module)

    known = set(factory.engines)
    for raw in registrations:
        registration = parse_registration(raw)
        if registration.name in known:
            raise BridgeRefusal(
                "engine_registration_conflict",
                f"engine name {registration.name!r} is already registered",
            )
        try:
            factory.add_engine(
                registration.name, registration.module, registration.class_name
            )
        except (ImportError, AttributeError, ModuleNotFoundError) as exc:
            raise BridgeRefusal(
                "plugin_missing",
                f"cannot register {raw!r} from the installed Python environment",
            ) from exc
        known.add(registration.name)
        registered.append(raw)
    return {"loaded_modules": loaded, "registered_engines": registered}


@dataclass(frozen=True)
class Projection:
    native_kind: str
    emitted_kind: str
    lines: tuple[str, ...]
    lossy: bool = False
    conversion: str | None = None


def _fraction_text(value: Any) -> str:
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator not in (None, 0, 1):
        return f"{numerator}/{denominator}"
    if numerator is not None and denominator == 1:
        return str(numerator)
    return str(value)


def _action_text(action_instance: Any) -> str:
    action = getattr(action_instance, "action", None)
    name = getattr(action, "name", None)
    if not name:
        raise BridgeRefusal(
            "malformed_action_instance",
            "planner returned an action instance without a canonical action name",
        )
    parameters = tuple(getattr(action_instance, "actual_parameters", ()) or ())
    rendered = " ".join(str(parameter) for parameter in parameters)
    return f"({name}{(' ' + rendered) if rendered else ''})"


def _sequential_projection(plan: Any, *, native_kind: str) -> Projection | None:
    actions = getattr(plan, "actions", None)
    if actions is None:
        return None
    return Projection(
        native_kind=native_kind,
        emitted_kind="sequential",
        lines=tuple(_action_text(action) for action in actions),
    )


def _temporal_projection(plan: Any, *, native_kind: str) -> Projection | None:
    timed_actions = getattr(plan, "timed_actions", None)
    if timed_actions is None:
        return None
    lines: list[str] = []
    for entry in timed_actions:
        if len(entry) != 3:
            raise BridgeRefusal(
                "malformed_timed_action",
                "planner returned a timed action outside the (start, action, duration) contract",
            )
        start, action, duration = entry
        line = f"{_fraction_text(start)}: {_action_text(action)}"
        if duration is not None:
            line += f" [{_fraction_text(duration)}]"
        lines.append(line)
    return Projection(
        native_kind=native_kind,
        emitted_kind="time_triggered",
        lines=tuple(lines),
    )


def project_plan(plan: Any, problem: Any, *, mode: str = "auto") -> Projection:
    """Project a UP plan into the textual candidate boundary consumed by MFW/VAL."""
    native_kind = str(getattr(plan, "kind", type(plan).__name__))

    projection = _sequential_projection(plan, native_kind=native_kind)
    if projection is None:
        projection = _temporal_projection(plan, native_kind=native_kind)

    action_plan = getattr(plan, "action_plan", None)
    if projection is None and action_plan is not None:
        nested = project_plan(action_plan, problem, mode=mode)
        projection = Projection(
            native_kind=native_kind,
            emitted_kind=nested.emitted_kind,
            lines=nested.lines,
            lossy=True,
            conversion="hierarchical_action_plan",
        )

    if projection is None and hasattr(plan, "convert_to"):
        try:
            from unified_planning.plans import PlanKind

            converted = plan.convert_to(PlanKind.SEQUENTIAL_PLAN, problem)
        except Exception:  # The next typed refusal preserves the failed edge.
            converted = None
        if converted is not None and converted is not plan:
            nested = project_plan(converted, problem, mode=mode)
            projection = Projection(
                native_kind=native_kind,
                emitted_kind=nested.emitted_kind,
                lines=nested.lines,
                lossy=True,
                conversion="deterministic_sequential_linearization",
            )

    if projection is None:
        raise BridgeRefusal(
            "unrepresentable_plan_kind",
            f"plan kind {native_kind!r} has no safe MFW textual candidate projection",
        )
    if mode == "classical" and projection.emitted_kind != "sequential":
        raise BridgeRefusal(
            "temporal_plan_on_classical_rail",
            "a time-triggered plan cannot enter the MFW classical projection rail",
        )
    return projection


def write_candidate(path: Path, projection: Projection) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(projection.lines) + ("\n" if projection.lines else ""), encoding="utf-8")


def _distribution_versions(names: Iterable[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in names:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


_DISTRIBUTIONS = (
    "unified-planning",
    "up-pyperplan",
    "up-tamer",
    "up-enhsp",
    "up-fast-downward",
    "up-lpg",
    "up-fmap",
    "up-aries",
    "up-symk",
    "up-spiderplan",
    "tamerlite",
    "up-paraspace",
)

_OPERATION_PROBES = (
    "oneshot_planner",
    "anytime_planner",
    "plan_validator",
    "compiler",
    "replanner",
    "plan_repairer",
    "portfolio_selector",
    "action_selector",
    "sequential_simulator",
)


def catalog(
    *, registrations: Iterable[str] = (), load_modules: Iterable[str] = ()
) -> dict[str, Any]:
    try:
        from unified_planning.environment import get_environment
    except ImportError as exc:
        raise BridgeRefusal("dependency_missing", "unified-planning is not installed") from exc

    factory = get_environment().factory
    plugin_admission = admit_plugins(
        factory, registrations=registrations, load_modules=load_modules
    )
    engines: list[dict[str, Any]] = []
    for name in sorted(factory.engines):
        engine_class = factory.engine(name)
        operations = []
        for operation in _OPERATION_PROBES:
            probe = getattr(engine_class, f"is_{operation}", None)
            try:
                supported = bool(probe()) if probe is not None else False
            except Exception:
                supported = False
            if supported:
                operations.append(operation)
        engines.append({"name": name, "operations": operations})
    return {
        "schema": "urn:mfw:pypi-planner-catalog:v1",
        "framework": "unified-planning",
        "distributions": _distribution_versions(_DISTRIBUTIONS),
        "plugin_admission": plugin_admission,
        "engines": engines,
    }


def solve(
    *,
    domain: Path,
    problem_path: Path,
    plan_path: Path,
    engine: str | None,
    mode: str,
    timeout: float | None,
    registrations: Iterable[str] = (),
    load_modules: Iterable[str] = (),
) -> dict[str, Any]:
    try:
        from unified_planning.io import PDDLReader
        from unified_planning.shortcuts import OneshotPlanner
    except ImportError as exc:
        raise BridgeRefusal("dependency_missing", "unified-planning is not installed") from exc

    from unified_planning.environment import get_environment

    plugin_admission = admit_plugins(
        get_environment().factory,
        registrations=registrations,
        load_modules=load_modules,
    )
    parsed = PDDLReader().parse_problem(str(domain), str(problem_path))
    planner_args = {"problem_kind": parsed.kind} if engine in (None, "", "auto") else {"name": engine}
    with OneshotPlanner(**planner_args) as planner:
        solve_args = {} if timeout is None else {"timeout": timeout}
        result = planner.solve(parsed, **solve_args)

    selected_engine = getattr(result, "engine_name", None) or getattr(planner, "name", None) or engine or "auto"
    status = str(getattr(result, "status", "unknown"))
    plan = getattr(result, "plan", None)
    if plan is None:
        return {
            "schema": "urn:mfw:pypi-planner-run:v1",
            "status": "no_candidate",
            "engine": selected_engine,
            "planner_status": status,
            "candidate": None,
            "plugin_admission": plugin_admission,
        }

    projection = project_plan(plan, parsed, mode=mode)
    write_candidate(plan_path, projection)
    sidecar = plan_path.with_suffix(plan_path.suffix + ".json")
    evidence = {
        "schema": "urn:mfw:pypi-planner-run:v1",
        "status": "found",
        "engine": selected_engine,
        "planner_status": status,
        "candidate": str(plan_path),
        "native_plan_kind": projection.native_kind,
        "emitted_plan_kind": projection.emitted_kind,
        "lossy_projection": projection.lossy,
        "conversion": projection.conversion,
        "step_count": len(projection.lines),
        "plugin_admission": plugin_admission,
    }
    sidecar.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence["evidence_sidecar"] = str(sidecar)
    return evidence

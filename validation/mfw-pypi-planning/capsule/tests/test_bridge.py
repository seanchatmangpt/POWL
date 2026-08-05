from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from mfw_pypi_planner.bridge import (
    BridgeRefusal,
    admit_plugins,
    parse_registration,
    project_plan,
    write_candidate,
)
from mfw_pypi_planner.cli import main


class Action:
    def __init__(self, name: str):
        self.name = name


class ActionInstance:
    def __init__(self, name: str, *parameters: str):
        self.action = Action(name)
        self.actual_parameters = parameters


class Sequential:
    kind = "SEQUENTIAL_PLAN"

    def __init__(self):
        self.actions = [ActionInstance("move", "a", "b"), ActionInstance("finish")]


class Temporal:
    kind = "TIME_TRIGGERED_PLAN"

    def __init__(self):
        self.timed_actions = [(0, ActionInstance("load", "truck"), 2), (2, ActionInstance("drive"), 3)]


class Hierarchical:
    kind = "HIERARCHICAL_PLAN"
    action_plan = Sequential()


class Unknown:
    kind = "CONTINGENT_PLAN"


class BridgeTests(unittest.TestCase):
    def test_sequential_projection_and_write(self):
        projection = project_plan(Sequential(), object(), mode="classical")
        self.assertEqual(projection.lines, ("(move a b)", "(finish)"))
        self.assertFalse(projection.lossy)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.plan"
            write_candidate(path, projection)
            self.assertEqual(path.read_text(), "(move a b)\n(finish)\n")

    def test_temporal_projection(self):
        projection = project_plan(Temporal(), object(), mode="temporal")
        self.assertEqual(projection.emitted_kind, "time_triggered")
        self.assertEqual(projection.lines[0], "0: (load truck) [2]")

    def test_hierarchical_projection_names_information_loss(self):
        projection = project_plan(Hierarchical(), object())
        self.assertTrue(projection.lossy)
        self.assertEqual(projection.conversion, "hierarchical_action_plan")

    def test_temporal_plan_refused_on_classical_rail(self):
        with self.assertRaisesRegex(BridgeRefusal, "classical projection rail") as context:
            project_plan(Temporal(), object(), mode="classical")
        self.assertEqual(context.exception.reason, "temporal_plan_on_classical_rail")

    def test_unrepresentable_kind_is_typed_refusal(self):
        with self.assertRaises(BridgeRefusal) as context:
            project_plan(Unknown(), object())
        self.assertEqual(context.exception.reason, "unrepresentable_plan_kind")

    def test_registration_is_canonical_and_admitted(self):
        registration = parse_registration("tamerlite=tamerlite.engine:TamerLite")
        self.assertEqual(registration.name, "tamerlite")

        class Factory:
            engines = []

            def __init__(self):
                self.added = []

            def add_engine(self, name, module, class_name):
                self.added.append((name, module, class_name))

        factory = Factory()
        evidence = admit_plugins(
            factory, registrations=["tamerlite=tamerlite.engine:TamerLite"]
        )
        self.assertEqual(factory.added, [("tamerlite", "tamerlite.engine", "TamerLite")])
        self.assertEqual(
            evidence["registered_engines"],
            ["tamerlite=tamerlite.engine:TamerLite"],
        )

    def test_invalid_or_conflicting_registration_is_refused(self):
        with self.assertRaises(BridgeRefusal) as invalid:
            parse_registration("not a registration")
        self.assertEqual(invalid.exception.reason, "invalid_engine_registration")

        class Factory:
            engines = ["pyperplan"]

            def add_engine(self, name, module, class_name):
                raise AssertionError("conflicting engine must not be registered")

        with self.assertRaises(BridgeRefusal) as conflict:
            admit_plugins(
                Factory(), registrations=["pyperplan=other.module:Planner"]
            )
        self.assertEqual(conflict.exception.reason, "engine_registration_conflict")

    def test_cli_dependency_failure_is_json_and_typed(self):
        # The local unit lane intentionally does not require Unified Planning.
        # catalog either succeeds in an enriched environment or emits a typed dependency refusal.
        with tempfile.TemporaryFile(mode="w+") as stream:
            import contextlib
            with contextlib.redirect_stdout(stream):
                code = main(["catalog"])
            stream.seek(0)
            value = json.load(stream)
        self.assertIn(code, (0, 3))
        self.assertIn("schema", value)


if __name__ == "__main__":
    unittest.main()

"""Executable POWL 2.0 research and wasm4pm-compat boundary contract."""

import pytest

from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.choice_graph import ChoiceGraph
from powl.objects.tagged_powl.partial_order import PartialOrder


def test_transitions_preserve_duplicate_labels_and_tau() -> None:
    first = Activity(label="Approve")
    second = Activity(label="Approve")
    silent = Activity(label=None)

    assert first is not second
    assert first.label == second.label == "Approve"
    assert silent.is_silent()
    assert silent.to_dict()["label"] is None


def test_partial_order_dag_denotes_strict_reachability_relation() -> None:
    first = Activity(label="A")
    second = Activity(label="B")
    third = Activity(label="C")
    model = PartialOrder(
        nodes=[first, second, third],
        edges=[(first, second), (second, third)],
    )

    model.validate()
    closure = model.get_transitive_closure()

    assert closure.has_edge(first, second)
    assert closure.has_edge(second, third)
    assert closure.has_edge(first, third)
    assert len(model.to_dict()["edges"]) == 2


def test_partial_order_canonicalizes_materialized_closure() -> None:
    first = Activity(label="A")
    second = Activity(label="B")
    third = Activity(label="C")
    model = PartialOrder(
        nodes=[first, second, third],
        edges=[(first, second), (second, third), (first, third)],
    )

    model.validate_and_remove_transitive_edges()

    assert model.get_edges() == {(first, second), (second, third)}
    assert model.get_transitive_closure().has_edge(first, third)


def test_choice_graph_admits_cycles_with_unique_artificial_boundaries() -> None:
    do = Activity(label="Do")
    redo = Activity(label="Redo")
    model = ChoiceGraph(
        nodes=[do, redo],
        edges=[(do, redo), (redo, do)],
        start_nodes=[do],
        end_nodes=[do],
    )

    model.validate_connectivity()
    payload = model.to_dict()

    assert model.start_nodes() == {do}
    assert model.end_nodes() == {do}
    assert len(payload["start_nodes"]) == 1
    assert len(payload["end_nodes"]) == 1
    assert len(payload["edges"]) == 2


def test_choice_graph_refuses_nodes_outside_start_to_end_paths() -> None:
    admitted = Activity(label="Admitted")
    orphan = Activity(label="Orphan")
    model = ChoiceGraph(
        nodes=[admitted, orphan],
        start_nodes=[admitted],
        end_nodes=[admitted],
    )

    with pytest.raises(ValueError, match="every user node must lie on a path"):
        model.validate_connectivity()


def test_tagged_dictionary_shape_matches_wasm4pm_compat_adapter() -> None:
    first = Activity(
        label="Approve",
        organization="Operations",
        role="Reviewer",
        attributes={"instance": 1},
    )
    second = Activity(label=None)
    model = PartialOrder(nodes=[first, second], edges=[(first, second)])

    payload = model.to_dict()

    assert set(payload) == {
        "type",
        "min_freq",
        "max_freq",
        "nodes",
        "edges",
        "attributes",
    }
    assert payload["type"] == "PartialOrder"
    assert {node["type"] for node in payload["nodes"]} == {"Activity"}
    assert {node["label"] for node in payload["nodes"]} == {"Approve", None}
    observable = next(node for node in payload["nodes"] if node["label"] == "Approve")
    assert observable["organization"] == "Operations"
    assert observable["role"] == "Reviewer"
    assert observable["attributes"] == {"instance": 1}

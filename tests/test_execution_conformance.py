"""Real Chicago-style tests for :mod:`powl.execution.conformance`. No
mocks: every model is a real ``TaggedPOWL`` structure (reusing
``test_execution_paper_examples.py``'s retailer production-subprocess
helper), and every observed sequence is either read off a real ``replay()``
run or a real, deliberately hand-constructed sequence -- assertions are on
the real ``ConformanceResult`` returned by ``check_conformance``."""

from __future__ import annotations

from powl.execution import ConformanceResult, check_conformance, replay
from powl.objects.tagged_powl.activity import Activity
from powl.objects.tagged_powl.builders import xor

from test_execution_paper_examples import _build_production_subprocess


def _never_repeat(node, completed):
    return False


def test_a_real_valid_trace_of_the_production_subprocess_fits():
    production, _ = _build_production_subprocess()

    def chooser(node, options):
        raise AssertionError("the production subprocess has no choice points")

    steps = replay(production, chooser=chooser, repeat_decider=_never_repeat)
    observed = tuple(step.node.label for step in steps)

    result = check_conformance(production, observed)

    assert isinstance(result, ConformanceResult)
    assert result.fits is True
    assert result.divergence_index is None
    assert result.divergence_label is None
    assert tuple(step.node.label for step in result.fired_prefix) == observed


def test_a_real_wrong_label_at_a_known_position_is_reported_exactly():
    production, _ = _build_production_subprocess()

    def chooser(node, options):
        raise AssertionError("the production subprocess has no choice points")

    steps = replay(production, chooser=chooser, repeat_decider=_never_repeat)
    real_labels = list(step.node.label for step in steps)

    # Inject a real, deliberate wrong label at a known position (index 2).
    injected_index = 2
    observed = tuple(real_labels[:injected_index]) + ("Not A Real Activity",) + tuple(
        real_labels[injected_index + 1 :]
    )

    result = check_conformance(production, observed)

    assert result.fits is False
    assert result.divergence_index == injected_index
    assert result.divergence_label == "Not A Real Activity"
    # Everything strictly before the divergence really did fire.
    assert tuple(step.node.label for step in result.fired_prefix) == tuple(
        real_labels[:injected_index]
    )


def test_a_real_valid_strict_prefix_of_a_full_trace_fits():
    """Strict prefix replay: stopping the observed sequence early, at a
    point that still matches everything seen so far, is a valid prefix of a
    real trace -- fits=True, per this module's documented scoping (no
    finality check; see conformance.py's module docstring)."""
    production, _ = _build_production_subprocess()

    def chooser(node, options):
        raise AssertionError("the production subprocess has no choice points")

    steps = replay(production, chooser=chooser, repeat_decider=_never_repeat)
    real_labels = tuple(step.node.label for step in steps)
    assert len(real_labels) > 1  # sanity: there is something to truncate

    prefix = real_labels[:-1]  # stop one activity short of the full trace

    result = check_conformance(production, prefix)

    assert result.fits is True
    assert result.divergence_index is None
    assert result.divergence_label is None
    assert tuple(step.node.label for step in result.fired_prefix) == prefix


def test_choice_graph_matching_the_chosen_branch_fits():
    in_stock = Activity(label="in-stock-path")
    production_path = Activity(label="production-path")
    model = xor([in_stock, production_path])

    result = check_conformance(model, ("in-stock-path",))

    assert result.fits is True
    assert result.divergence_index is None
    assert result.divergence_label is None
    assert tuple(step.node.label for step in result.fired_prefix) == ("in-stock-path",)


def test_choice_graph_naming_the_unchosen_branch_diverges_at_the_real_point():
    """Once the ``xor``'s real min_freq/max_freq==1 budget is spent on the
    matched ``in-stock-path`` branch, the model has nothing left to offer --
    naming the other, unchosen branch's activity next is a real divergence,
    reported exactly where it occurs (index 1), not silently accepted."""
    in_stock = Activity(label="in-stock-path")
    production_path = Activity(label="production-path")
    model = xor([in_stock, production_path])

    result = check_conformance(model, ("in-stock-path", "production-path"))

    assert result.fits is False
    assert result.divergence_index == 1
    assert result.divergence_label == "production-path"
    assert tuple(step.node.label for step in result.fired_prefix) == ("in-stock-path",)


def test_choice_graph_naming_a_label_outside_the_model_diverges_at_index_zero():
    in_stock = Activity(label="in-stock-path")
    production_path = Activity(label="production-path")
    model = xor([in_stock, production_path])

    # Neither real branch produces this label at all -- the exact real
    # divergence must be reported at index 0.
    result = check_conformance(model, ("not-a-real-branch",))

    assert result.fits is False
    assert result.divergence_index == 0
    assert result.divergence_label == "not-a-real-branch"
    assert result.fired_prefix == ()

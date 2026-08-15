"""Real, no-mock tests for ``powl.conversion.to_powl.from_pn.converter.is_separable``.

is_separable defers entirely to convert_workflow_net_to_powl's own success or
failure (see that function's docstring): it is the paper's own stated
completeness criterion (H. Kourani et al., "Hierarchical Decomposition of
Separable Workflow-Nets", Sections 4/5 -- the algorithm is complete for
separable WF-nets, i.e. succeeds iff the input is separable), not an
independently-verified structural separability check.

FIXED BUG (previously documented here as an "honest discrepancy"):

Figure 2 of the paper (p. 12) is explicitly captioned "A free-choice WF-net
that is not separable" and is used in Definition 3.13's discussion as the
paper's own negative example. tests/fixtures/paper_wf_nets.py's
build_figure_2_non_separable_net() is a faithful, arc-for-arc transcription
of that figure: a single source/sink WF-net, verified sound and safe with
pm4py's woflan checker, that structurally contains a PT-handle from the
place produced by "a" to transition "d" (the two disjoint paths
a->e->p_d_pre_d->d and a->b->p_c_pre_d->d) -- exactly the structural feature
the paper itself names as characteristic of non-separable nets.

Running this fixture through ``convert_workflow_net_to_powl`` used to
succeed (``is_separable`` returned ``(True, "")``), contradicting the
paper's classification. The root cause was a real, confirmed bug in
converter.py's preprocessing step (preprocessing.preprocess): its
``pre1 == pre2 and len(common_post) > 0`` branch (and its symmetric
``post1 == post2 and len(common_pre) > 0`` counterpart) merged two places
into a silent-choice (XOR) structure whenever they shared a preset/postset,
without checking whether that shared preset was actually a single AND-split
transition producing tokens in *both* places on every firing (or, in the
symmetric case, an AND-join transition consuming from both). For this
fixture, "a" AND-splits into both p_a and p_b_in on every firing -- they are
never alternatives -- so the merge silently collapsed real concurrency into
exclusive choice, changing the net's language and eliminating the PT-handle
before the recursive partial-order/choice-graph mining ever saw it.

The fix adds a guard to both branches: if any transition in the shared
preset (respectively shared postset) already has both p1 and p2 in its own
postset (respectively preset), the merge is unsound and is skipped, falling
through to the next check instead. With the fix, ``is_separable`` now
returns ``(False, "Unique local start property is violated!")`` on this
fixture, matching the paper's own classification of Figure 2 as
non-separable. See test 2 below for the current, verified assertion.
"""

from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.petri_net.utils import petri_utils as pn_util

from powl.conversion.to_powl.from_pn.converter import is_separable
from fixtures.paper_wf_nets import (
    build_figure_1a_order_fulfillment_net,
    build_figure_2_non_separable_net,
)


def _place(net: PetriNet, name: str) -> PetriNet.Place:
    p = PetriNet.Place(name)
    net.places.add(p)
    return p


def _trans(net: PetriNet, name: str, label) -> PetriNet.Transition:
    t = PetriNet.Transition(name, label)
    net.transitions.add(t)
    return t


def _arc(net: PetriNet, source, target) -> None:
    pn_util.add_arc_from_to(source, target, net)


def _build_pure_sequence_net() -> PetriNet:
    """src -A-> p1 -B-> sink : a trivial separable (marked-graph) WF-net."""
    net = PetriNet("pure_sequence")
    src = _place(net, "p_source")
    p1 = _place(net, "p1")
    sink = _place(net, "p_sink")
    t_a = _trans(net, "t_a", "A")
    t_b = _trans(net, "t_b", "B")
    _arc(net, src, t_a)
    _arc(net, t_a, p1)
    _arc(net, p1, t_b)
    _arc(net, t_b, sink)
    return net


def _build_pure_xor_choice_net() -> PetriNet:
    """src -> {A, B} -> sink : a trivial separable (state-machine) WF-net."""
    net = PetriNet("pure_xor_choice")
    src = _place(net, "p_source")
    sink = _place(net, "p_sink")
    t_a = _trans(net, "t_a", "A")
    t_b = _trans(net, "t_b", "B")
    _arc(net, src, t_a)
    _arc(net, t_a, sink)
    _arc(net, src, t_b)
    _arc(net, t_b, sink)
    return net


def _build_single_and_split_join_net() -> PetriNet:
    """src -(silent AND-split)-> {A || B} -(silent AND-join)-> sink."""
    net = PetriNet("single_and_split_join")
    src = _place(net, "p_source")
    sink = _place(net, "p_sink")
    p_a_branch = _place(net, "p_a_branch")
    p_b_branch = _place(net, "p_b_branch")
    p_a_done = _place(net, "p_a_done")
    p_b_done = _place(net, "p_b_done")
    t_split = _trans(net, "t_split", None)
    t_a = _trans(net, "t_a", "A")
    t_b = _trans(net, "t_b", "B")
    t_join = _trans(net, "t_join", None)

    _arc(net, src, t_split)
    _arc(net, t_split, p_a_branch)
    _arc(net, t_split, p_b_branch)
    _arc(net, p_a_branch, t_a)
    _arc(net, p_b_branch, t_b)
    _arc(net, t_a, p_a_done)
    _arc(net, t_b, p_b_done)
    _arc(net, p_a_done, t_join)
    _arc(net, p_b_done, t_join)
    _arc(net, t_join, sink)
    return net


def test_figure_1a_order_fulfillment_net_is_separable():
    """The paper's own positive example (Figure 1a) really converts."""
    net = build_figure_1a_order_fulfillment_net()
    result = is_separable(net)
    assert result == (True, "")


def test_figure_2_net_correctly_classified_as_non_separable():
    """The paper's own explicitly-stated negative example (Figure 2).

    The paper classifies this net as NOT separable. With the preprocessing
    bug fixed (see the module docstring above), this converter now agrees:
    is_separable returns (False, ...) on a faithful transcription of that
    figure.
    """
    net = build_figure_2_non_separable_net()
    result = is_separable(net)
    assert result[0] is False and result[1], (
        "Expected is_separable to classify the paper's Figure 2 as "
        f"non-separable with a non-empty reason, got: {result!r}."
    )


def test_pure_sequence_net_is_separable():
    net = _build_pure_sequence_net()
    result = is_separable(net)
    assert result == (True, "")


def test_pure_xor_choice_net_is_separable():
    net = _build_pure_xor_choice_net()
    result = is_separable(net)
    assert result == (True, "")


def test_single_and_split_join_net_is_separable():
    net = _build_single_and_split_join_net()
    result = is_separable(net)
    assert result == (True, "")

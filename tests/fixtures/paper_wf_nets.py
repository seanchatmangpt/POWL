"""Real pm4py PetriNet fixtures reconstructed from:

    H. Kourani et al., "Hierarchical Decomposition of Separable Workflow-Nets"
    (Figure 1a, p. 3; Figure 2, p. 12; Definition 3.13, p. 11)

Both nets are built directly as ``pm4py.objects.petri_net.obj.PetriNet``
instances using ``pm4py.objects.petri_net.utils.petri_utils.add_arc_from_to``.
No existing PetriNet-building test helper was found anywhere under
``tests/`` or ``powl/`` (checked via ``grep -rln "PetriNet(" tests/ powl/``
before writing this module), so both builders are written from scratch here.

build_figure_1a_order_fulfillment_net()
----------------------------------------
The retailer order-fulfillment WF-net from Figure 1a. Structure (transition
labels in quotes, silent transitions unlabeled):

    src -"Place New Order"-> p_after_order -"Check Stock Availability"-> p_choice

    XOR at p_choice:
      p_choice -"Cancel Order"-> sink
      p_choice -(silent AND-split)-> p_g, p_s
          p_g -"Gather Production Materials"-> p_ag
          p_s -"Schedule Production"-> p_as1, p_as2
          p_ag, p_as1 -"Execute Production"-> p_ae
          p_as2 -"Notify Customer"-> p_an
          p_ae, p_an -(silent AND-join)-> p_pre_collect
          p_pre_collect -"Collect Items from Stock"-> p_after_collect
          p_after_collect -"Ship Order"-> sink

This is a direct WF-net encoding of the paper's own text (Sec. 1, p. 2-3):
non-block-structured concurrency in the production subprocess ("Execute
Production" depends on both "Gather Production Materials" and "Schedule
Production", while "Notify Customer" is only constrained by "Schedule
Production"), nested inside a top-level XOR between cancellation and
shipment. Verified sound and safe with pm4py's woflan checker and with this
repo's own ``validate_workflow_net`` before being committed here.

build_figure_2_non_separable_net()
-----------------------------------
The paper's own explicit counterexample (Figure 2, p. 12, captioned "A
free-choice WF-net that is not separable"), transcribed arc-for-arc from the
figure and from Definition 3.13's discussion of it ("a choice that depends
on the state of a parallel branch without synchronization"):

    p_source -"a"-> p_a, p_b_in                         (AND-split)
    p_a -"e"->  (e's preset is {p_a, p_b_in})
    p_b_in -"e"->
    p_a -"b"-> p_c_pre_d
    p_b_in -"c"-> p_d_pre_d
    t_e -> p_c_pre_d, p_d_pre_d                          (e reconnects to the
                                                           same merge point b/c feed)
    p_c_pre_d, p_d_pre_d -"d"-> p_after_d -"f"-> p_sink   (AND-join)

This is a valid, safe, sound WF-net (verified below and with woflan) with a
single source and single sink, and it structurally exhibits a PT-handle from
p_a to t_d (the two disjoint paths p_a->e->p_d_pre_d->d and
p_a->b->p_c_pre_d->d), which is exactly the structural signature the paper
itself names (Sec. 3, p. 12) as characteristic of non-separable nets.

FIXED BUG NOTE (see also the module docstring of tests/test_separability.py):
despite matching the figure's described arcs and despite exhibiting a real
PT-handle, this specific net used to convert *successfully* under this
repository's ``convert_workflow_net_to_powl``, contradicting the paper's
classification of Figure 2 as non-separable. The root cause was a real,
confirmed bug in preprocessing.preprocess()'s place-merging heuristic: its
``pre1 == pre2 and len(common_post) > 0`` branch merged p_a's two AND-split
output places (p_a and p_b_in, both produced by every firing of "a") into a
silent-choice (XOR) place, even though "a" is an AND-split into both of
them, not a choice between them -- this silently collapsed real concurrency
into exclusive choice, changing the net's language and eliminating the
PT-handle before separability analysis ever saw it. The bug has been fixed
by adding a guard: the merge is now skipped whenever a transition in the
shared preset/postset already AND-splits/AND-joins into/from both
candidate places. With the fix, this fixture now correctly converts as
non-separable, matching the paper. See tests/test_separability.py for the
exact verified result.
"""

from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.petri_net.utils import petri_utils as pn_util


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


def build_figure_1a_order_fulfillment_net() -> PetriNet:
    """Build the retailer order-fulfillment WF-net from Figure 1a (p. 3)."""
    net = PetriNet("figure_1a_order_fulfillment")

    src = _place(net, "p_source")
    sink = _place(net, "p_sink")

    t_place_order = _trans(net, "t_place_order", "Place New Order")
    p_after_order = _place(net, "p_after_order")
    t_check_stock = _trans(net, "t_check_stock", "Check Stock Availability")
    p_choice = _place(net, "p_choice")

    t_cancel = _trans(net, "t_cancel", "Cancel Order")

    silent_split = _trans(net, "silent_split_production", None)
    p_g = _place(net, "p_gather_branch")
    p_s = _place(net, "p_schedule_branch")

    t_gather = _trans(net, "t_gather", "Gather Production Materials")
    t_schedule = _trans(net, "t_schedule", "Schedule Production")
    p_after_gather = _place(net, "p_after_gather")
    p_after_schedule_1 = _place(net, "p_after_schedule_1")
    p_after_schedule_2 = _place(net, "p_after_schedule_2")

    t_execute = _trans(net, "t_execute", "Execute Production")
    t_notify = _trans(net, "t_notify", "Notify Customer")
    p_after_execute = _place(net, "p_after_execute")
    p_after_notify = _place(net, "p_after_notify")

    silent_join = _trans(net, "silent_join_production", None)
    p_pre_collect = _place(net, "p_pre_collect")

    t_collect = _trans(net, "t_collect", "Collect Items from Stock")
    p_after_collect = _place(net, "p_after_collect")
    t_ship = _trans(net, "t_ship", "Ship Order")

    arc = lambda a, b: _arc(net, a, b)

    arc(src, t_place_order)
    arc(t_place_order, p_after_order)
    arc(p_after_order, t_check_stock)
    arc(t_check_stock, p_choice)

    # top-level XOR: cancel, or proceed to production + shipment
    arc(p_choice, t_cancel)
    arc(t_cancel, sink)

    arc(p_choice, silent_split)
    arc(silent_split, p_g)
    arc(silent_split, p_s)

    # AND-concurrency: Gather Production Materials || Schedule Production
    arc(p_g, t_gather)
    arc(p_s, t_schedule)
    arc(t_gather, p_after_gather)
    arc(t_schedule, p_after_schedule_1)
    arc(t_schedule, p_after_schedule_2)

    # Execute Production depends on both Gather and Schedule
    arc(p_after_gather, t_execute)
    arc(p_after_schedule_1, t_execute)
    arc(t_execute, p_after_execute)

    # Notify Customer depends only on Schedule
    arc(p_after_schedule_2, t_notify)
    arc(t_notify, p_after_notify)

    arc(p_after_execute, silent_join)
    arc(p_after_notify, silent_join)
    arc(silent_join, p_pre_collect)

    arc(p_pre_collect, t_collect)
    arc(t_collect, p_after_collect)
    arc(p_after_collect, t_ship)
    arc(t_ship, sink)

    return net


def build_figure_2_non_separable_net() -> PetriNet:
    """Build the WF-net from Figure 2 (p. 12), captioned in the paper as
    "A free-choice WF-net that is not separable".
    """
    net = PetriNet("figure_2_non_separable")

    p_source = _place(net, "p_source")
    p_a = _place(net, "p_a")  # top place produced by a
    p_b_in = _place(net, "p_b_in")  # bottom place produced by a
    p_c_pre_d = _place(net, "p_c_pre_d")  # top place before d
    p_d_pre_d = _place(net, "p_d_pre_d")  # bottom place before d
    p_after_d = _place(net, "p_after_d")
    p_sink = _place(net, "p_sink")

    t_a = _trans(net, "t_a", "a")
    t_b = _trans(net, "t_b", "b")
    t_c = _trans(net, "t_c", "c")
    t_d = _trans(net, "t_d", "d")
    t_e = _trans(net, "t_e", "e")
    t_f = _trans(net, "t_f", "f")

    arc = lambda a, b: _arc(net, a, b)

    arc(p_source, t_a)
    arc(t_a, p_a)
    arc(t_a, p_b_in)

    # e is fed directly by both places produced by a
    arc(p_a, t_e)
    arc(p_b_in, t_e)

    # b and c each consume one of the two places, feeding the merge before d
    arc(p_a, t_b)
    arc(p_b_in, t_c)
    arc(t_b, p_c_pre_d)
    arc(t_c, p_d_pre_d)

    # e also connects directly to that same merge point
    arc(t_e, p_c_pre_d)
    arc(t_e, p_d_pre_d)

    arc(p_c_pre_d, t_d)
    arc(p_d_pre_d, t_d)

    arc(t_d, p_after_d)
    arc(p_after_d, t_f)
    arc(t_f, p_sink)

    return net

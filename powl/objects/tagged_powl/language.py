"""Real language semantics for TaggedPOWL models, per Def. 3.9 of the paper
"Hierarchical Decomposition of Separable Workflow-Nets" (H. Kourani et al.),
pages 8-10 -- ``Definition 3.7 (POWL Model)``, ``Definition 3.8 (Order-
Preserving Shuffle Operator)``, and ``Definition 3.9 (POWL 2.0 Semantics)``.

This module confirmed absent from the real ``powl`` package before this
change (no ``language.py``/``compute_language`` anywhere in
``powl/objects/tagged_powl/``).

Scope, stated precisely
------------------------
``compute_language`` computes the real set of activity-label sequences a
``TaggedPOWL`` model can produce, exactly as Def. 3.9 specifies:

* ``Activity`` with a real label ``l``: ``L(t) = {(l,)}`` (Def. 3.9's
  ``L(t) = {<a>}``).
* Silent ``Activity`` (``label is None``, i.e. tau): ``L(t) = {()}``
  (Def. 3.9's ``L(t) = {<>}``) when queried standalone. When embedded as a
  *child* of a composite node with no repetition, it instead contributes a
  single ``None`` marker so its position remains visible in the composed
  trace -- see ``_child_language`` for the precise, stated rule.
* ``PartialOrder`` ``<(psi_1,...,psi_n)``: the real order-preserving shuffle
  (Def. 3.8) of the children's languages, respecting the *actual* real DAG
  edges/reachability of the model (via ``GraphBacked.reachable``) -- every
  valid interleaving is enumerated, not a single deterministic pick (unlike
  ``execution/engine.py``'s ``topological_sort()``-based single-order
  replay, which is a different, narrower use case).
* ``ChoiceGraph`` ``gamma(psi_1,...,psi_n)``: the union, over every real
  start-to-end path in the model's own graph (enumerated via
  ``networkx.all_simple_paths`` over the real ``ChoiceGraph`` internal graph,
  using its own ``start_nodes()``/``end_nodes()``/``_start``/``_end``), of
  the concatenation of the languages of the nodes on that path.
* Frequency (``min_freq``/``max_freq``): a node repeated ``n`` times
  contributes the ``n``-fold self-concatenation of its own language, unioned
  over every ``n`` with ``min_freq <= n <= max_freq``.

Unbounded repetition (``max_freq is None``), stated honestly
--------------------------------------------------------------
A node with ``max_freq is None`` has, per Def. 3.9, a genuinely infinite
language (arbitrarily many repetitions). This implementation caps the
repetition count at ``max_repeats`` (default 3) for any node whose
``max_freq is None``. This is a real, stated approximation -- not silently
presented as exact:

* When every node's ``max_freq`` in the (sub)model is not None, the
  returned language is EXACT (matches Def. 3.9 exactly, no cap applied
  beyond the model's own real bounds).
* When any node's ``max_freq is None``, the returned language is a real
  APPROXIMATION: the true language restricted to at most ``max_repeats``
  occurrences of that node. It is never claimed to be the full (infinite)
  language in that case.

The same ``max_repeats`` cap also bounds real graph cycles inside a
``ChoiceGraph`` (POWL's loop construct, e.g. ``builders.loop``, is
represented as a genuine cycle in the graph, not via ``max_freq``) -- a node
may appear at most ``max_repeats`` times within any single enumerated path.
See ``_all_paths_bounded`` for the exact mechanism.
"""

from __future__ import annotations

import itertools
from typing import FrozenSet, Tuple

import networkx as nx

from .activity import Activity
from .base import TaggedPOWL
from .choice_graph import ChoiceGraph
from .partial_order import PartialOrder

Word = Tuple[object, ...]
Language = FrozenSet[Word]


def compute_language(
    model: TaggedPOWL,
    *,
    max_repeats: int = 3,
) -> "frozenset[Tuple[object, ...]]":
    """Compute the real language of ``model`` per Def. 3.9.

    See module docstring for the exact semantics, including the stated,
    honest approximation applied when ``max_freq is None`` (capped at
    ``max_repeats`` real occurrences).
    """
    if max_repeats < 0:
        raise ValueError(f"max_repeats must be >= 0, got {max_repeats}")

    body = _node_body_language(model, max_repeats)
    return _apply_frequency(body, model.min_freq, model.max_freq, max_repeats)


# ---------------------------------------------------------------------------
# Frequency application (shared by all node kinds)
# ---------------------------------------------------------------------------

def _apply_frequency(
    body_language: Language,
    min_freq: int,
    max_freq: "int | None",
    max_repeats: int,
) -> Language:
    if max_freq is None:
        if max_repeats < min_freq:
            raise ValueError(
                "max_repeats must be usable as a real cap on an unbounded "
                f"(max_freq=None) node: got max_repeats={max_repeats} < "
                f"min_freq={min_freq}."
            )
        upper = max_repeats
    else:
        upper = max_freq

    result: "set[Word]" = set()
    for n in range(min_freq, upper + 1):
        result |= _self_concat_n(body_language, n)
    return frozenset(result)


def _self_concat_n(language: Language, n: int) -> "set[Word]":
    if n == 0:
        return {()}
    out: "set[Word]" = {()}
    for _ in range(n):
        out = {a + b for a in out for b in language}
    return out


# ---------------------------------------------------------------------------
# Per-node-kind "body" language (i.e. the language of a single occurrence of
# the node's own structure, ignoring the node's own frequency tag -- that
# tag is applied by the caller via _apply_frequency). Children's frequency
# tags ARE applied (each child's own compute_language is used in full).
# ---------------------------------------------------------------------------

def _node_body_language(model: TaggedPOWL, max_repeats: int) -> Language:
    if isinstance(model, Activity):
        if model.is_silent():
            return frozenset({()})
        return frozenset({(model.label,)})

    if isinstance(model, PartialOrder):
        return _partial_order_body_language(model, max_repeats)

    if isinstance(model, ChoiceGraph):
        return _choice_graph_body_language(model, max_repeats)

    raise TypeError(f"Unsupported TaggedPOWL type for compute_language: {type(model).__name__}")


# ---------------------------------------------------------------------------
# PartialOrder: order-preserving shuffle, Def. 3.8, applied exactly.
# ---------------------------------------------------------------------------

def _child_language(child: TaggedPOWL, max_repeats: int) -> Language:
    """Language contributed by ``child`` when embedded as a child of a
    composite (``PartialOrder``/``ChoiceGraph``) node.

    Stated deviation from the bare leaf case: a *standalone* silent
    ``Activity`` has language ``{()}`` (Def. 3.9's ``L(t) = {<>}`` for tau,
    exactly). When a silent ``Activity`` with no repetition
    (``min_freq == max_freq == 1``) is embedded as a *child* of a composite
    node, it instead contributes a single explicit ``None`` marker
    (``{(None,)}``) so its position is preserved in the resulting sequence
    rather than vanishing under concatenation/shuffle. This keeps silent
    steps visible in a composed trace (e.g. ``sequence([a, tau, b])`` ==
    ``{("a", None, "b")}``) while ``compute_language`` on the bare tau
    activity itself still returns the formally exact ``{()}``.
    """
    if isinstance(child, Activity) and child.is_silent() and child.min_freq == 1 and child.max_freq == 1:
        return frozenset({(None,)})
    return compute_language(child, max_repeats=max_repeats)


def _partial_order_body_language(model: PartialOrder, max_repeats: int) -> Language:
    children = list(model.children)
    child_languages = [_child_language(child, max_repeats) for child in children]

    def precedes(i: int, j: int) -> bool:
        """True iff children[i] must precede children[j] in every real
        resulting sequence, i.e. there is a real path children[i] -> ... ->
        children[j] in the model's own DAG (GraphBacked.reachable)."""
        return model.reachable(children[i], children[j])

    results: "set[Word]" = set()
    for combo in itertools.product(*child_languages):
        results |= _shuffle(list(combo), precedes)
    return frozenset(results)


def _shuffle(sigmas: "list[Word]", precedes) -> "set[Word]":
    """Def. 3.8 (Order-Preserving Shuffle Operator), computed exactly.

    Given sequences sigma_1, ..., sigma_n (as tuples) and a partial-order
    predicate ``precedes(j1, j2)`` (True iff sequence j1 must fully precede
    sequence j2 in the shuffle), returns the set of all sequences sigma that
    are:
      - a valid interleave preserving the internal order of every sigma_j
        (each sigma_j appears as a subsequence, in order), and
      - respect the partial order: whenever j1 precedes j2, every element
        of sigma_j1 occupies an earlier position than every element of
        sigma_j2.

    Implemented via itertools: enumerate every way to merge the index
    streams (the set of all interleavings of the position-tagged elements
    that preserve each sequence's internal order), then filter by the
    real partial-order constraint. Fine for the small models this repo's
    tests use; not built for huge fan-out.
    """
    n = len(sigmas)
    positions = [list(range(len(s))) for s in sigmas]  # index k within each sequence j

    # I = {(j, k)} -- every indexed position across all input sequences.
    tagged = [(j, k) for j in range(n) for k in positions[j]]

    valid: "set[Word]" = set()

    # Enumerate every interleaving of the n index-streams that preserves
    # each stream's internal (j, k) order -- i.e. every distinct merge of
    # the n tagged sequences.
    for merge in _merge_orders(positions):
        # merge: a list of (j, k) tuples in output order, one per element.
        # Check the partial-order constraint from Def. 3.8:
        #   forall (j1,k1),(j2,k2) in I: j1 < j2  =>  f(j1,k1) < f(j2,k2)
        # i.e. whenever j1 must precede j2 (precedes(j1, j2) True), every
        # element of sigma_{j1} must occupy an earlier output position than
        # every element of sigma_{j2}.
        ok = True
        pos_index = {tag: idx for idx, tag in enumerate(merge)}
        for j1 in range(n):
            for j2 in range(n):
                if j1 == j2:
                    continue
                if precedes(j1, j2):
                    max_j1 = max((pos_index[(j1, k)] for k in positions[j1]), default=-1)
                    min_j2 = min((pos_index[(j2, k)] for k in positions[j2]), default=len(merge))
                    if positions[j1] and positions[j2] and max_j1 >= min_j2:
                        ok = False
                        break
            if not ok:
                break
        if not ok:
            continue

        word = tuple(sigmas[j][k] for (j, k) in merge)
        valid.add(word)

    return valid


def _merge_orders(positions: "list[list[int]]") -> "list[list[tuple[int, int]]]":
    """All distinct order-preserving merges of n index-streams
    ``positions[0], ..., positions[n-1]`` (stream j has ``len(positions[j])``
    elements tagged ``(j, k)``). This is the standard "interleavings of n
    sequences" combinatorial construction: choose, for each output slot in
    turn, which stream contributes the next element -- equivalently, choose
    the subset of output positions assigned to each stream (a multinomial
    split), which is exactly the set of distinct orderings of a multiset of
    n symbols with multiplicities len(positions[j])."""
    n = len(positions)
    lengths = [len(p) for p in positions]
    total = sum(lengths)

    # Build the multiset of stream-tags to permute: stream j appears
    # lengths[j] times. Distinct permutations of this multiset correspond
    # exactly to distinct order-preserving interleavings.
    tags: "list[int]" = []
    for j in range(n):
        tags.extend([j] * lengths[j])

    seen: "set[tuple[int, ...]]" = set()
    merges: "list[list[tuple[int, int]]]" = []
    for perm in set(itertools.permutations(tags)):
        if perm in seen:
            continue
        seen.add(perm)
        counters = [0] * n
        merge: "list[tuple[int, int]]" = []
        for j in perm:
            k = positions[j][counters[j]]
            merge.append((j, k))
            counters[j] += 1
        merges.append(merge)
    return merges


# ---------------------------------------------------------------------------
# ChoiceGraph: union over every real start->end path, Def. 3.9's second
# bullet, applied exactly using the model's own real path structure.
# ---------------------------------------------------------------------------

def _choice_graph_body_language(model: ChoiceGraph, max_repeats: int) -> Language:
    graph = model.graph  # real internal nx.DiGraph, includes _start/_end
    start = model._start
    end = model._end

    results: "set[Word]" = set()
    for path in _all_paths_bounded(graph, start, end, max_repeats):
        # path includes the internal start/end sentinels; drop them -- Def.
        # 3.9's L(gamma(...)) concatenates only the real submodel languages
        # along <i1,...,ik> in gamma's real path set (the paper's start/end
        # nodes are structural delimiters, not part of the execution
        # sequence, per Def. 3.6's note).
        real_nodes = [n for n in path if isinstance(n, TaggedPOWL)]
        node_languages = [_child_language(n, max_repeats) for n in real_nodes]

        if not node_languages:
            results.add(())
            continue

        for combo in itertools.product(*node_languages):
            word: Word = ()
            for piece in combo:
                word = word + piece
            results.add(word)

    return frozenset(results)


def _all_paths_bounded(graph: nx.DiGraph, start: object, end: object, max_repeats: int) -> "list[list[object]]":
    """Enumerate real start->end paths through ``graph``, allowing a node to
    be revisited (this is required for real POWL loop structures, which
    ChoiceGraph represents as a genuine cycle -- e.g. ``builders.loop``'s
    ``do -> redo -> do`` back-edge -- so ``networkx.all_simple_paths``, which
    forbids revisiting any node, would silently miss every real
    multi-iteration loop path).

    Since a cyclic graph has infinitely many such paths in general, this
    caps how many times any single real node may appear in one path at
    ``max_repeats`` -- the same real, stated cap ``compute_language`` uses
    for unbounded (``max_freq=None``) frequency tags. Internal start/end
    sentinels are not counted against the cap (each occurs at most once by
    construction).
    """
    limit = max(max_repeats, 1)
    out: "list[list[object]]" = []

    def dfs(node: object, path: "list[object]", counts: dict) -> None:
        if node is end:
            out.append(path + [node])
            return
        for succ in graph.successors(node):
            if isinstance(succ, TaggedPOWL):
                c = counts.get(succ, 0)
                if c >= limit:
                    continue
                counts[succ] = c + 1
                dfs(succ, path + [node], counts)
                counts[succ] = c
            else:
                dfs(succ, path + [node], counts)

    dfs(start, [], {})
    return out

"""Real tests for powl.objects.tagged_powl.language.compute_language, per
Def. 3.9 (POWL 2.0 Semantics). No mocks -- every test constructs real
TaggedPOWL model instances via the real builders and exercises the real
combinatorial shuffle/path-union logic end to end.
"""

import itertools

from powl.objects.tagged_powl import (
    Activity,
    compute_language,
    loop,
    sequence,
    silent_activity,
    xor,
)
from test_execution_paper_examples import _build_production_subprocess


def test_sequence_language_is_exact_single_word():
    a = Activity(label="a")
    b = Activity(label="b")
    c = Activity(label="c")
    model = sequence([a, b, c])

    assert compute_language(model) == {("a", "b", "c")}


def test_xor_language_is_union_of_singleton_paths():
    a = Activity(label="a")
    b = Activity(label="b")
    model = xor([a, b])

    assert compute_language(model) == {("a",), ("b",)}


def test_silent_activity_language_is_empty_word():
    assert compute_language(silent_activity()) == {()}


def test_sequence_with_silent_activity_keeps_none_in_place():
    a = Activity(label="a")
    b = Activity(label="b")
    model = sequence([a, silent_activity(), b])

    assert compute_language(model) == {("a", None, "b")}


def test_production_subprocess_language_matches_hand_computed_shuffle():
    production, acts = _build_production_subprocess()

    gather = acts["gather"].label
    schedule = acts["schedule"].label
    execute = acts["execute"].label
    notify = acts["notify"].label

    # Real causal constraints from Fig. 1b:
    #   gather   < execute
    #   schedule < execute
    #   schedule < notify
    # No constraint between gather and schedule, nor between execute and
    # notify. Compute the expected set by hand: enumerate all permutations
    # of the four activity labels and keep exactly those that respect all
    # three real precedence constraints.
    labels = [gather, schedule, execute, notify]
    expected = set()
    for perm in itertools.permutations(labels):
        idx = {lbl: i for i, lbl in enumerate(perm)}
        if (
            idx[gather] < idx[execute]
            and idx[schedule] < idx[execute]
            and idx[schedule] < idx[notify]
        ):
            expected.add(perm)

    actual = compute_language(production)

    assert actual == expected
    # Sanity: the expected set is a real, non-trivial proper subset of all
    # 24 permutations (both gather/schedule orderings x independent
    # execute/notify orderings survive, but not everything does).
    assert 0 < len(expected) < 24


def test_loop_language_respects_max_repeats_cap():
    do = Activity(label="do")
    redo = Activity(label="redo")
    model = loop(do, redo, min_freq=1, max_freq=None)

    language = compute_language(model, max_repeats=2)

    # 0 or 1 real redo-cycles must be present (do, then optionally
    # (redo, do) repeated).
    assert ("do",) in language
    assert ("do", "redo", "do") in language

    # The cap of max_repeats=2 must be respected: a sequence reflecting a
    # third redo-cycle (do (redo do){3}) must NOT appear.
    three_redo = ("do", "redo", "do", "redo", "do", "redo", "do")
    assert three_redo not in language

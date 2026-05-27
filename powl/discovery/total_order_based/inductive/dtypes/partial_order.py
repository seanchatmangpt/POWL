from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from typing import Any, Collection, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Literal, Union

import pandas as pd
from pm4py.algo.discovery.inductive.dtypes.im_ds import IMDataStructureUVCL
from pm4py.objects.dfg.obj import DFG


ArtifactWeighting = Literal["normalized", "unit"]

IndexPair = Tuple[int, int]


@dataclass(frozen=True)
class PartialOrderTrace:
    """Event-indexed partially ordered trace variant.

    ``activities`` is an ordered list of activity labels. The position in this
    list is the event identity, therefore duplicate labels are allowed.

    ``order`` is a strict partial order over event indices. It is assumed to be
    transitive and irreflexive. For example::

        activities = ("a", "b", "c", "a")
        order = {(0, 1), (0, 2), (0, 3), (1, 3), (2, 3)}

    represents a trace where the first ``a`` happens before ``b`` and ``c``,
    ``b`` and ``c`` are unordered, and both happen before the final ``a``.
    """

    activities: Tuple[Any, ...]
    order: FrozenSet[IndexPair] = frozenset()

    def __post_init__(self):
        activities = tuple(self.activities)
        order = frozenset((int(i), int(j)) for i, j in self.order)

        object.__setattr__(self, "activities", activities)
        object.__setattr__(self, "order", order)

    def __len__(self) -> int:
        return len(self.activities)

    @property
    def labels(self) -> Tuple[Any, ...]:
        return self.activities

    @property
    def is_empty(self) -> bool:
        return len(self.activities) == 0

    @property
    def alphabet(self) -> set:
        return set(self.activities)

    @cached_property
    def predecessors(self) -> Tuple[FrozenSet[int], ...]:
        preds: List[set] = [set() for _ in range(len(self))]
        for i, j in self.order:
            preds[j].add(i)
        return tuple(frozenset(p) for p in preds)

    @cached_property
    def successors(self) -> Tuple[FrozenSet[int], ...]:
        succs: List[set] = [set() for _ in range(len(self))]
        for i, j in self.order:
            succs[i].add(j)
        return tuple(frozenset(s) for s in succs)

    @cached_property
    def transitive_reduction_edges(self) -> FrozenSet[IndexPair]:
        return frozenset(
            (i, j)
            for i, j in self.order
            if not (self.successors[i] & self.predecessors[j])
        )

    @cached_property
    def minimal_indices(self) -> FrozenSet[int]:
        """Events with no predecessors.
        """
        return frozenset(i for i in range(len(self)) if not self.predecessors[i])

    @cached_property
    def maximal_indices(self) -> FrozenSet[int]:
        """Events with no successors.
        """
        return frozenset(i for i in range(len(self)) if not self.successors[i])

    @classmethod
    def empty(cls) -> "PartialOrderTrace":
        return cls(tuple(), frozenset())

    @classmethod
    def from_timestamped_events(
        cls,
        activities: Sequence[Any],
        timestamps: Sequence[Any],
        time_window: Optional[timedelta | pd.Timedelta],
    ) -> "PartialOrderTrace":
        """Create a general POT from timestamped events.

        Event ``i`` precedes event ``j`` iff::

            timestamp_i + time_window < timestamp_j

        Hence, exactly equal timestamps are unordered for ``time_window=0``;
        with a positive window, events whose timestamps are too close are also
        unordered.

        """
        if len(activities) != len(timestamps):
            raise ValueError("activities and timestamps must have the same length")
        if len(activities) == 0:
            return cls.empty()

        if time_window is not None:
            time_window = _normalize_time_window(time_window)

        indexed_events = [
            (original_index, activity, pd.Timestamp(timestamp))
            for original_index, (activity, timestamp)
            in enumerate(zip(activities, timestamps))
        ]

        indexed_events.sort(
            key=lambda item: (
                item[2],  # timestamp
                item[1],  # activity label
                item[0],  # original index as final deterministic tie-breaker
            )
        )

        sorted_activities = tuple(
            activity
            for _, activity, _
            in indexed_events
        )

        sorted_times = tuple(
            timestamp
            for _, _, timestamp
            in indexed_events
        )

        order = set()

        for i, time_i in enumerate(sorted_times):
            threshold = time_i if time_window is None else time_i + time_window
            first_j = bisect_right(sorted_times, threshold)

            for j in range(first_j, len(sorted_times)):
                order.add((i, j))

        # for i, time_i in enumerate(sorted_times):
        #     for j, time_j in enumerate(sorted_times):
        #         if i == j:
        #             continue
        #
        #         if _strictly_before_with_window(time_i, time_j, time_window):
        #             order.add((i, j))

        return cls(sorted_activities, frozenset(order))


    def precedes(self, i: int, j: int) -> bool:
        return (i, j) in self.order

    def concurrent(self, i: int, j: int) -> bool:
        return i != j and (i, j) not in self.order and (j, i) not in self.order


    def combined_project(self, group: Collection[Any]) -> "PartialOrderTrace":
        """Combined projection for partial-order traces.

        All events belonging to the group will be combined into a single sub-POT.
        """
        group_set = set(group)
        kept_old_indices = [i for i, activity in enumerate(self.activities) if activity in group_set]
        if not kept_old_indices:
            return PartialOrderTrace.empty()

        return self._create_sub_trace(kept_old_indices)


    def split_project(self, group: Collection[Any]) -> List["PartialOrderTrace"]:
        """Conservative split projection for partial-order traces.

        Start with selected events. Events are placed in the same segment if they
        are connected by evidence of belonging together: either concurrency or a
        cover relation in the transitive reduction.
        """
        group_set = set(group)
        if not group_set:
            return []

        group_indices = [
            i
            for i, activity in enumerate(self.activities)
            if activity in group_set
        ]

        if not group_indices:
            return []

        reduction = self.transitive_reduction_edges

        def should_merge_events(id1: int, id2: int) -> bool:
            return (
                    self.concurrent(id1, id2)
                    or (id1, id2) in reduction
                    or (id2, id1) in reduction
            )

        # Build merge graph.
        merge_graph = {
            i: set()
            for i in group_indices
        }

        for pos, i in enumerate(group_indices):
            for j in group_indices[pos + 1:]:
                if should_merge_events(i, j):
                    merge_graph[i].add(j)
                    merge_graph[j].add(i)

        # Connected components of the merge graph.
        components: List[List[int]] = []
        visited = set()

        for start in group_indices:
            if start in visited:
                continue

            stack = [start]
            visited.add(start)
            component = []

            while stack:
                current = stack.pop()
                component.append(current)

                for neighbor in merge_graph[current]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)

            components.append(component)

        def make_subtrace(old_indices: List[int]) -> "PartialOrderTrace":
            old_indices = sorted(old_indices)
            return self._create_sub_trace(old_indices)

        return [
            make_subtrace(component)
            for component in sorted(components, key=lambda c: min(c))
        ]

    def _create_sub_trace(self, old_indices):
        old_to_new = {old_i: new_i for new_i, old_i in enumerate(old_indices)}
        new_activities = tuple(self.activities[i] for i in old_indices)

        new_order = frozenset(
            (old_to_new[i], old_to_new[j])
            for i in old_indices
            for j in self.successors[i]
            if j in old_indices
        )

        return PartialOrderTrace(new_activities, new_order)


def _normalize_time_window(window: timedelta | pd.Timedelta) -> pd.Timedelta:
    """Normalize the timestamp tolerance window.

    We intentionally require a real timedelta object instead of accepting
    numbers or strings, because numeric windows are ambiguous and can hide
    mistakes.
    """

    if isinstance(window, timedelta):
        window = pd.Timedelta(window)
    elif not isinstance(window, pd.Timedelta):
        raise TypeError(
            "time_window must be None, datetime.timedelta, or pandas.Timedelta"
        )

    if window < pd.Timedelta(0):
        raise ValueError("time_window must be non-negative")

    return window


# def _strictly_before_with_window(time_i: Any, time_j: Any, window: Optional[pd.Timedelta]) -> bool:
#     if window is None:
#         return pd.Timestamp(time_i) < pd.Timestamp(time_j)
#     else:
#         return pd.Timestamp(time_i) + window < pd.Timestamp(time_j)


def log_to_pot_variants(
    df: pd.DataFrame,
    activity_key: str,
    timestamp_key: str,
    case_id_key: str,
    time_window: Optional[Union[timedelta, pd.Timedelta]],
) -> Counter:
    traces = []

    for _, case_df in df.groupby(case_id_key, sort=False):
        case_df = case_df.sort_values(
            by=[timestamp_key, activity_key],
            kind="stable",
        )

        trace = PartialOrderTrace.from_timestamped_events(
            activities=case_df[activity_key].tolist(),
            timestamps=case_df[timestamp_key].tolist(),
            time_window=time_window,
        )
        traces.append(trace)

    return get_partial_order_variants(traces)


def get_partial_order_variants(traces: Iterable[PartialOrderTrace]) -> Counter:
    """
    Convert POTs to a Counter-based variant representation.
    """
    log = Counter()
    for variant in traces:
        key = PartialOrderTrace(variant.activities, variant.order)
        log[key] += 1
    return log


def discover_dfg_efg_pot(
        log: Counter[PartialOrderTrace],
        weighting: ArtifactWeighting = "unit",
) -> Tuple[DFG, Counter]:
    """
    Discover a full-frequency start/end/DFG/EFG artifacts from partial-order variants.
    """
    dfg = DFG()
    efg = Counter()
    for trace, trace_freq in _iter_pot_variants(log):
        if len(trace) == 0:
            continue
        if weighting == "normalized":
            start, end, local_dfg, local_efg = _trace_normalized_expanded_counters(trace)
        elif weighting == "unit":
            start, end, local_dfg, local_efg = _trace_unit_expanded_counters(trace)
        else:
            raise ValueError("weighting must be 'unit' or 'normalized'")
        for activity, value in start.items():
            dfg.start_activities[activity] += trace_freq * value
        for activity, value in end.items():
            dfg.end_activities[activity] += trace_freq * value
        for pair, value in local_dfg.items():
            dfg.graph[pair] += trace_freq * value
        for pair, value in local_efg.items():
            efg[pair] += trace_freq * value
    return dfg, efg


def _iter_pot_variants(log: Counter[PartialOrderTrace]):
    for trace, freq in log.items():
        yield trace, freq


def _trace_unit_expanded_counters(
    trace: PartialOrderTrace,
) -> Tuple[Counter, Counter, Counter, Counter]:
    """Unit-weight expanded start/end/DFG/EFG counters.

    * For ordered event pairs i < j, add full mass 1.0 to label_i -> label_j.
    * For concurrent event pairs i || j, add full unit mass in both directions:
      label_i -> label_j += 1.0
      label_j -> label_i += 1.0
    """
    labels = trace.activities
    order = trace.order
    n = len(trace)

    start = Counter()
    end = Counter()
    dfg = Counter()
    efg = Counter()

    # start
    for i in trace.minimal_indices:
        start[labels[i]] += 1.0

    # end
    for i in trace.maximal_indices:
        end[labels[i]] += 1.0

    # causal DFG edges
    for i, j in trace.transitive_reduction_edges:
        dfg[(labels[i], labels[j])] += 1.0

    # pairwise EFG and concurrent DFG
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in order:
                efg[(labels[i], labels[j])] += 1.0
            elif (j, i) in order:
                efg[(labels[j], labels[i])] += 1.0
            else:
                # DFG edges
                dfg[(labels[i], labels[j])] += 1.0
                dfg[(labels[j], labels[i])] += 1.0
                # EFG edges
                efg[(labels[i], labels[j])] += 1.0
                efg[(labels[j], labels[i])] += 1.0

    return start, end, dfg, efg



def _trace_normalized_expanded_counters(
    trace: PartialOrderTrace,
) -> Tuple[Counter, Counter, Counter, Counter]:
    """Trace-normalized expanded start/end/DFG/EFG counters.

    Semantics:

    DFG/start/end:
    * Add a hidden SOURCE with edges to all minimal events.
    * Add a hidden SINK with edges from all maximal events.
    * Add cover relations from the transitive reduction.
    * Add concurrency as bidirectional local possibilities.
    * Normalize outgoing mass per source node/event inside this trace.

    EFG:
    * For ordered event pairs i < j, add full mass 1 to label_i -> label_j.
    * For concurrent event pairs i || j, split pair mass equally:
      label_i -> label_j += 0.5
      label_j -> label_i += 0.5
    """
    labels = trace.activities
    n = len(trace)

    start = Counter()
    end = Counter()
    dfg = Counter()
    efg = Counter()

    if n == 0:
        return start, end, dfg, efg

    source = -1
    sink = n

    # ------------------------------------------------------------------
    # DFG + start/end via hidden SOURCE/SINK and local outgoing normalization
    # ------------------------------------------------------------------
    expanded_edges = set()

    # SOURCE -> minimal events
    for i in trace.minimal_indices:
        expanded_edges.add((source, i))

    # maximal events -> SINK
    for i in trace.maximal_indices:
        expanded_edges.add((i, sink))

    # Direct causal edges
    expanded_edges.update(trace.transitive_reduction_edges)

    order = trace.order

    # ------------------------------------------------------------------
    # EFG via pairwise eventual-order evidence
    # Concurrent events as bidirectional local possibilities for the DFG
    # ------------------------------------------------------------------
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in order:
                efg[(labels[i], labels[j])] += 1.0

            elif (j, i) in order:
                efg[(labels[j], labels[i])] += 1.0

            else:
                # i || j: split the unordered pair mass equally
                efg[(labels[i], labels[j])] += 0.5
                efg[(labels[j], labels[i])] += 0.5
                # add DFG expanded edges
                expanded_edges.add((i, j))
                expanded_edges.add((j, i))

    outgoing = {}
    for src, tgt in expanded_edges:
        outgoing.setdefault(src, []).append(tgt)

    for src, targets in outgoing.items():
        weight = 1.0 / len(targets)

        for tgt in targets:
            if src == source:
                # Hidden SOURCE -> activity
                start[labels[tgt]] += weight

            elif tgt == sink:
                # activity -> hidden SINK
                end[labels[src]] += weight

            else:
                # activity -> activity
                dfg[(labels[src], labels[tgt])] += weight

    return start, end, dfg, efg


class IMDataStructurePOT(IMDataStructureUVCL):
    """Inductive-miner data structure for partially ordered trace variants."""

    def __init__(
        self,
        obj: Counter[PartialOrderTrace],
        dfg: Optional[DFG] = None,
        efg: Optional[Counter] = None,
    ):
        super().__init__(obj)

        if (dfg is None) != (efg is None):
            raise ValueError("dfg and efg must be provided together")

        if dfg is not None and efg is not None:
            self._dfg = dfg
            self._efg = efg
        else:
            artifacts = discover_dfg_efg_pot(obj)
            self._dfg = artifacts[0]
            self._efg = artifacts[1]

    @property
    def dfg(self) -> DFG:
        return self._dfg

    @property
    def efg(self) -> Counter:
        return self._efg


def is_pot_data_structure(obj: Any) -> bool:
    return isinstance(obj, IMDataStructurePOT)


def combined_project_pot_on_groups(
    log: Counter[PartialOrderTrace],
    groups: List[Collection[Any]],
    keep_empty: bool = True,
) -> List[IMDataStructurePOT]:
    projected_logs = [Counter() for _ in groups]
    for trace, freq in log.items():
        for i, group in enumerate(groups):
            projected = trace.combined_project(group)
            if keep_empty or len(projected) > 0:
                projected_logs[i][projected] += freq
    return [IMDataStructurePOT(projected_log) for projected_log in projected_logs]


def split_project_pot_on_groups(
        log: Counter[PartialOrderTrace],
        groups: List[Collection[Any]]
) -> List[IMDataStructurePOT]:
    projected_logs = [Counter() for _ in groups]
    for trace, freq in log.items():
        for i, group in enumerate(groups):
            for projected in trace.split_project(group):
                if len(projected) > 0:
                    projected_logs[i][projected] += freq
    return [IMDataStructurePOT(projected_log) for projected_log in projected_logs]

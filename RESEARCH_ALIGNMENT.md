# POWL 2.0 research contract

This fork admits the structural contract in Kourani, Park, and van der Aalst,
*Hierarchical Decomposition of Separable Workflow-Nets*, arXiv:2602.15739v3,
Definitions 3.6–3.9.

## Executable interpretation

- `Activity(label=str)` is an observable transition.
- `Activity(label=None)` is a silent transition labeled tau.
- Object identity distinguishes transitions that share the same activity label.
- `PartialOrder` stores a finite DAG. DAG reachability is the strict partial-order
  relation used by the order-preserving shuffle semantics. A transitive reduction
  and its materialized closure therefore denote the same research-level order.
- `ChoiceGraph` stores artificial start/end boundaries internally, permits cycles
  among child POWL models, and validates that every child lies on a start-to-end path.
- Composite children are recursively nested `TaggedPOWL` models.

## wasm4pm compatibility boundary

`wasm4pm-compat` consumes the public nested dictionary returned by `to_dict()`.
The contract fixture covers activities, silent transitions, duplicate labels,
partial-order DAGs, choice cycles, boundary indices, organization/role annotations,
and arbitrary JSON-compatible attributes.

Frequency tags are an implementation extension with language semantics. Consumers
must run `expand_frequency_tags` before projecting a tagged model into the core
POWL 2.0 compatibility contract; they must not silently reinterpret frequency as
metadata.

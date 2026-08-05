# POWL Lean 4 formalization

This directory is a proof-oriented model of the **entire repository surface**, not a second implementation of only the POWL notation.

## Boundary

The Python repository remains the executable discovery and visualization implementation. Lean owns the admitted mathematical objects and the proof obligations:

1. raw activity, partial-order, and choice-graph syntax;
2. frequency bounds and silent behavior;
3. graph reachability, acyclicity, transitive closure, and transitive reduction;
4. trace languages, sequence, concurrency, and iteration;
5. total-order, partial-order, DFG, and object-centric event inputs;
6. inductive discovery phases, variants, filters, cuts, base cases, and fall-throughs;
7. JSON validation and round-trip contracts;
8. Petri-net, BPMN, and process-tree translation contracts;
9. visualization and pool/lane projection obligations;
10. public API, UI-adapter, packaging, deployment, examples, and test coverage.

The principal architectural split is:

```text
Python object / JSON / event data
        ↓ parse
RawModel
        ↓ admit or refuse
Model := RawModel + WellFormed proof
        ↓ interpret
Language
        ↓ transform
conversion / discovery / normalization theorem
```

A mutable NetworkX graph therefore has no standing by itself. Standing begins only after its references, boundary conditions, acyclicity, and reduction obligations are admitted.

## Build

```bash
lake update
lake exe cache get
lake build
lake exe powlVerifier
```

`mathlib` and Lean are pinned together at `v4.32.1`.

## Verification rail

GitHub Actions runs:

- `lake build --wfail` through `leanprover/lean-action`;
- Lean's independent `leanchecker` environment verification;
- the Rust-based `nanoda` checker with `sorryAx` forbidden;
- the `powlVerifier` executable receipt.

## Proof-state discipline

The initial scaffold establishes typed domains and kernel proofs, but it does **not** claim all Python algorithms correct. Unproved repository claims are represented as explicit structures or predicates (`SoundMiner`, `CompleteFor`, `Translation.PreservesLanguage`, `Codec.RoundTrips`) rather than axioms disguised as completed theorems.

The next proof sequence is:

1. JSON codec round-trip and validator equivalence;
2. normalization language preservation for silent-node and frequency rewrites;
3. POWL-to-Petri-net language preservation;
4. workflow-net-to-POWL preservation and separable-net completeness;
5. inductive-miner soundness by base case, cut, filter, fall-through, and recursion;
6. choice-graph SCC and sequentialization preservation;
7. object-centric projection correctness.

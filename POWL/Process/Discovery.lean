import POWL.Model
import POWL.Process.EventLog

namespace POWL

namespace Discovery

/-- Public discovery variants exposed by the Python router. -/
inductive Variant
  | tree
  | bruteForce
  | maximal
  | dynamicClustering
  | decisionGraphMaximal
  | decisionGraphClustering
  | decisionGraphCyclic
  | decisionGraphCyclicStrict
  deriving DecidableEq, Repr

/-- A sum type makes the one-filter-at-a-time invariant unrepresentably false. -/
inductive Filtering
  | none
  | dfgFrequency (threshold : Rat)
  | dynamicOrder (threshold : Rat)
  | decreasingFactor (factor : Rat)
  deriving Repr

/-- Public discovery parameters. -/
structure Parameters where
  variant : Variant := .decisionGraphCyclic
  filtering : Filtering := .none
  keepOnlyCompletionEvents : Bool := true
  simplify : Bool := true
  timeOrdering : Bool := false
  deriving Repr

inductive InputKind
  | totalOrderLog
  | partialOrderLog
  | directlyFollowsGraph
  | objectCentricLog
  deriving DecidableEq, Repr

inductive Phase
  | import
  | orderEvents
  | removeIncompleteLifecycleEvents
  | emptyTraceCut
  | baseCase
  | cut
  | filter
  | fallThrough
  | recurse
  | normalize
  | validate
  deriving DecidableEq, Repr

inductive CutKind
  | sequence
  | xor
  | loop
  | concurrency
  | partialOrder
  | choiceGraph
  deriving DecidableEq, Repr

inductive BaseCase
  | emptyLog
  | singleActivity
  deriving DecidableEq, Repr

inductive FallThrough
  | flower
  | tauLoop
  | concurrency
  | emptyTraces
  deriving DecidableEq, Repr

inductive Refusal
  | unsupportedInput
  | invalidParameters
  | noFallThrough
  | nonDecreasingRecursion
  | validationFailed
  deriving DecidableEq, Repr

/-- Typed counterpart of the Python `SequenceSpec`, `XorSpec`, `LoopSpec`, and graph specs. -/
inductive InductiveSpec (Label : Type u)
  | resolved (model : RawModel Label)
  | sequence (arity : Nat)
  | xor (arity : Nat)
  | loop (arity : Nat)
  | partialOrder (arity : Nat) (edges : List (Nat × Nat))
  | choiceGraph
      (arity : Nat)
      (edges : List (Nat × Nat))
      (starts : List Nat)
      (ends : List Nat)
      (frequency : Frequency)

/-- One recursive decomposition emitted by a base case, cut, or fall-through. -/
structure Decomposition (Input Label : Type) where
  parent : Input
  spec : InductiveSpec Label
  children : List Input
  measure : Input → Nat
  decreases : ∀ child ∈ children, measure child < measure parent

/-- Generic miner interface. Successful results are admitted models, never bare candidates. -/
structure Miner (Input Label : Type) where
  discover : Parameters → Input → Except Refusal (Model Label)

/-- The semantic claim a miner must establish. -/
structure SoundMiner (Input Label : Type)
    (sem : Interpretation Label)
    (behavior : Input → Language Label)
    extends Miner Input Label where
  sound : ∀ params input model,
    discover params input = .ok model → sem.denote model.raw ⊆ behavior input

/-- Completeness is deliberately separate from soundness. -/
def CompleteFor {Input Label : Type}
    (sem : Interpretation Label)
    (behavior : Input → Language Label)
    (miner : Miner Input Label)
    (domain : Input → Prop) : Prop :=
  ∀ params input model,
    domain input → miner.discover params input = .ok model →
      behavior input ⊆ sem.denote model.raw

/-- A normalization request may be routed only after discovery returned an admitted model. -/
def SimplifiesAfterAdmission {Input Label : Type} (miner : Miner Input Label) : Prop :=
  ∀ params input model,
    miner.discover params input = .ok model → model.raw.WellFormed

end Discovery
end POWL

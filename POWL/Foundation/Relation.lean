import Mathlib

namespace POWL

/-- A graph relation independent of its mutable Python/NetworkX carrier. -/
structure Digraph (α : Type u) where
  edge : α → α → Prop

namespace Digraph

variable {α : Type u}

/-- Non-empty reachability. -/
def Reachable (g : Digraph α) : α → α → Prop := Relation.TransGen g.edge

/-- Reflexive reachability. -/
def ReachableOrEq (g : Digraph α) : α → α → Prop := Relation.ReflTransGen g.edge

/-- No node is reachable from itself through a non-empty path. -/
def Acyclic (g : Digraph α) : Prop := ∀ x, ¬ g.Reachable x x

/-- The edge relation itself is irreflexive. -/
def Irreflexive (g : Digraph α) : Prop := ∀ x, ¬ g.edge x x

/-- The edge relation is transitively closed. -/
def TransitivelyClosed (g : Digraph α) : Prop :=
  ∀ ⦃a b c⦄, g.edge a b → g.edge b c → g.edge a c

/-- An edge is redundant when another non-empty route has the same endpoints. -/
def RedundantEdge (g : Digraph α) (a b : α) : Prop :=
  g.edge a b ∧ ∃ c, c ≠ b ∧ g.edge a c ∧ g.ReachableOrEq c b

/-- This is the semantic obligation enforced by the repository's JSON validator. -/
def TransitivelyReduced (g : Digraph α) : Prop :=
  ∀ ⦃a b⦄, g.edge a b → ¬ g.RedundantEdge a b

end Digraph

/-- Kernel-level strict partial order. -/
structure StrictPartialOrder (α : Type u) extends Digraph α where
  irrefl : ∀ x, ¬ edge x x
  trans : ∀ ⦃a b c⦄, edge a b → edge b c → edge a c

namespace StrictPartialOrder

variable {α : Type u}

/-- Irreflexivity plus transitivity gives asymmetry. -/
theorem asymmetric (o : StrictPartialOrder α) ⦃a b : α⦄ (hab : o.edge a b) :
    ¬ o.edge b a := by
  intro hba
  exact o.irrefl a (o.trans hab hba)

/-- Every strict partial order is acyclic. -/
theorem acyclic (o : StrictPartialOrder α) : o.toDigraph.Acyclic := by
  intro x hcycle
  have collapse : ∀ {a b}, Relation.TransGen o.edge a b → o.edge a b := by
    intro a b path
    induction path with
    | single h => exact h
    | tail _ hbc hac => exact o.trans hac hbc
  exact o.irrefl x (collapse hcycle)

end StrictPartialOrder

/-- A finite indexed graph used by raw POWL composites and interchange formats. -/
structure IndexedGraph (β : Type u) where
  nodes : List β
  edges : List (Nat × Nat) := []
  starts : List Nat := []
  ends : List Nat := []

namespace IndexedGraph

variable {β : Type u}

/-- All references point into `nodes`. -/
def ReferencesInBounds (g : IndexedGraph β) : Prop :=
  (∀ e ∈ g.edges, e.1 < g.nodes.length ∧ e.2 < g.nodes.length) ∧
  (∀ i ∈ g.starts, i < g.nodes.length) ∧
  (∀ i ∈ g.ends, i < g.nodes.length)

/-- Relation induced by the serialized edge list. -/
def edgeRel (g : IndexedGraph β) (i j : Nat) : Prop := (i, j) ∈ g.edges

/-- The graph projected to its relation-theoretic carrier. -/
def asDigraph (g : IndexedGraph β) : Digraph Nat := ⟨g.edgeRel⟩

/-- Every user node lies on a start-to-end path. -/
def BoundaryConnected (g : IndexedGraph β) : Prop :=
  ∀ i, i < g.nodes.length →
    (∃ s ∈ g.starts, g.asDigraph.ReachableOrEq s i) ∧
    (∃ t ∈ g.ends, g.asDigraph.ReachableOrEq i t)

/-- Choice-graph boundary markers are themselves valid node references. -/
def HasBoundaries (g : IndexedGraph β) : Prop := g.starts ≠ [] ∧ g.ends ≠ []

end IndexedGraph
end POWL

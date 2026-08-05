import POWL.Foundation.Frequency
import POWL.Foundation.Relation
import POWL.Semantics.Language

namespace POWL

/-- The three runtime model types exposed by the repository. -/
inductive ModelType
  | activity
  | partialOrder
  | choiceGraph
  deriving DecidableEq, Repr

/-- Typed replacement for the open Python attributes dictionary. -/
structure Attributes where
  name : Option String := none
  description : Option String := none
  resource : Option String := none
  role : Option String := none
  cost : Option Int := none
  lifecycle : Option String := none
  extension : List (String × String) := []
  deriving Repr

/-- Activity node; `label = none` is τ. -/
structure Activity (Label : Type u) where
  label : Option Label
  organization : Option String := none
  role : Option String := none
  frequency : Frequency := Frequency.once
  attributes : Attributes := {}

namespace Activity

variable {Label : Type u}

def IsSilent (a : Activity Label) : Prop := a.label = none

def IsObservable (a : Activity Label) : Prop := ∃ label, a.label = some label

end Activity

/-- Untrusted recursive syntax decoded from Python objects or JSON. -/
inductive RawModel (Label : Type u)
  | activity (node : Activity Label)
  | partialOrder (frequency : Frequency) (graph : IndexedGraph (RawModel Label))
  | choiceGraph (frequency : Frequency) (graph : IndexedGraph (RawModel Label))

namespace RawModel

variable {Label : Type u}

def modelType : RawModel Label → ModelType
  | .activity _ => .activity
  | .partialOrder _ _ => .partialOrder
  | .choiceGraph _ _ => .choiceGraph

def frequency : RawModel Label → Frequency
  | .activity a => a.frequency
  | .partialOrder f _ => f
  | .choiceGraph f _ => f

/-- Admission relation. It is intentionally separate from raw syntax. -/
inductive WellFormed : RawModel Label → Prop
  | activity (a : Activity Label) : WellFormed (.activity a)
  | partialOrder
      (frequency : Frequency)
      (graph : IndexedGraph (RawModel Label))
      (references : graph.ReferencesInBounds)
      (acyclic : graph.asDigraph.Acyclic)
      (reduced : graph.asDigraph.TransitivelyReduced)
      (children : ∀ child ∈ graph.nodes, WellFormed child) :
      WellFormed (.partialOrder frequency graph)
  | choiceGraph
      (frequency : Frequency)
      (graph : IndexedGraph (RawModel Label))
      (references : graph.ReferencesInBounds)
      (boundaries : graph.HasBoundaries)
      (connected : graph.BoundaryConnected)
      (children : ∀ child ∈ graph.nodes, WellFormed child) :
      WellFormed (.choiceGraph frequency graph)

end RawModel

/-- Admitted POWL model: raw observation plus kernel-checkable standing. -/
structure Model (Label : Type u) where
  raw : RawModel Label
  admitted : raw.WellFormed

/-- A semantics is an explicit interpretation, not an accidental Python execution trace. -/
structure Interpretation (Label : Type u) where
  denote : RawModel Label → Language Label
  tau_law : ∀ a : Activity Label, a.IsSilent → denote (.activity a) = Language.epsilon
  activity_law : ∀ (a : Activity Label) (label : Label),
    a.label = some label → denote (.activity a) = Language.atom label

namespace Interpretation

variable {Label : Type u}

def Equivalent (sem : Interpretation Label) (left right : RawModel Label) : Prop :=
  sem.denote left = sem.denote right

/-- Normalization may change syntax but must preserve the denoted language. -/
def Preserves (sem : Interpretation Label)
    (normalize : RawModel Label → RawModel Label) : Prop :=
  ∀ model, sem.Equivalent (normalize model) model

end Interpretation
end POWL

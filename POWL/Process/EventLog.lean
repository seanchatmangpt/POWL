import POWL.Foundation.Relation

namespace POWL

inductive Lifecycle
  | start
  | complete
  | other (name : String)
  deriving DecidableEq, Repr

/-- Event record covering total-order, lifecycle, and object-centric inputs. -/
structure Event (Activity CaseId Timestamp ObjectType ObjectId : Type) where
  caseId : CaseId
  activity : Activity
  timestamp : Timestamp
  lifecycle : Option Lifecycle := none
  objects : List (ObjectType × ObjectId) := []
  attributes : List (String × String) := []
  deriving Repr

abbrev EventTrace (Activity CaseId Timestamp ObjectType ObjectId : Type) :=
  List (Event Activity CaseId Timestamp ObjectType ObjectId)

abbrev EventLog (Activity CaseId Timestamp ObjectType ObjectId : Type) :=
  List (EventTrace Activity CaseId Timestamp ObjectType ObjectId)

/-- Total-order trace projected to activity labels. -/
def activityTrace
    {Activity CaseId Timestamp ObjectType ObjectId : Type}
    (trace : EventTrace Activity CaseId Timestamp ObjectType ObjectId) : List Activity :=
  trace.map Event.activity

/-- Adjacency semantics underlying a directly-follows graph. -/
def DirectlyFollows {α : Type u} (trace : List α) (a b : α) : Prop :=
  ∃ front back, trace = front ++ [a, b] ++ back

/-- Reachability semantics underlying an eventually-follows graph. -/
def EventuallyFollows {α : Type u} (trace : List α) (a b : α) : Prop :=
  ∃ front middle back, trace = front ++ [a] ++ middle ++ [b] ++ back

/-- A trace whose event order is explicitly partial rather than inferred from one timestamp sort. -/
structure PartiallyOrderedTrace (Event : Type u) where
  events : List Event
  order : Digraph Nat
  referencesInBounds : ∀ i j, order.edge i j → i < events.length ∧ j < events.length
  acyclic : order.Acyclic

inductive ObjectRelationKind
  | related
  | divergent
  | convergent
  | deficient
  deriving DecidableEq, Repr

/-- Object-centric typing information attached to each activity. -/
structure ObjectCentricTyping (Activity ObjectType : Type) where
  hasType : Activity → ObjectRelationKind → ObjectType → Prop

end POWL

import POWL.Model

namespace POWL

namespace Process

/-- Minimal mathematical Petri-net carrier used by conversion theorems. -/
structure PetriNet (Place Transition : Type u) where
  pre : Place → Transition → Nat
  post : Transition → Place → Nat

abbrev Marking (Place : Type u) := Place → Nat

namespace PetriNet

variable {Place Transition : Type u}

def Enabled (net : PetriNet Place Transition) (marking : Marking Place)
    (transition : Transition) : Prop :=
  ∀ place, net.pre place transition ≤ marking place

def fire (net : PetriNet Place Transition)
    (marking : Marking Place) (transition : Transition) : Marking Place :=
  fun place => marking place - net.pre place transition + net.post transition place

end PetriNet

inductive BPMNNodeKind
  | startEvent
  | endEvent
  | task
  | exclusiveGateway
  | parallelGateway
  deriving DecidableEq, Repr

structure BPMN (Node : Type u) where
  kind : Node → BPMNNodeKind
  flow : Node → Node → Prop
  pool : Node → Option String := fun _ => none
  lane : Node → Option String := fun _ => none

inductive ProcessTree (Label : Type u)
  | tau
  | activity (label : Label)
  | sequence (children : List (ProcessTree Label))
  | xor (children : List (ProcessTree Label))
  | parallel (children : List (ProcessTree Label))
  | loop (body redo : ProcessTree Label)
  deriving Repr

end Process

namespace Conversion

/-- Translation bundled with its target-language semantics. -/
structure Translation (Source Target Label : Type) where
  translate : Source → Target
  sourceLanguage : Source → Language Label
  targetLanguage : Target → Language Label

namespace Translation

variable {A B C Label : Type}

/-- Language preservation is the principal conversion theorem. -/
def PreservesLanguage (t : Translation A B Label) : Prop :=
  ∀ source, t.targetLanguage (t.translate source) = t.sourceLanguage source

/-- Composition of verified translators remains verified. -/
def comp (ab : Translation A B Label) (bc : Translation B C Label) :
    Translation A C Label where
  translate := bc.translate ∘ ab.translate
  sourceLanguage := ab.sourceLanguage
  targetLanguage := bc.targetLanguage

/-- A reusable proof combinator for conversion pipelines. -/
theorem comp_preserves (ab : Translation A B Label) (bc : Translation B C Label)
    (hab : ab.PreservesLanguage) (hbc : bc.PreservesLanguage) :
    (ab.comp bc).PreservesLanguage := by
  intro source
  change bc.targetLanguage (bc.translate (ab.translate source)) = ab.sourceLanguage source
  rw [hbc, hab]

end Translation
end Conversion
end POWL

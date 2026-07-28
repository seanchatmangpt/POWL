import POWL.Model

namespace POWL

namespace Normalization

/-- Rewrite families implemented by `PartialOrder.normalize` and `ChoiceGraph.normalize`. -/
inductive RewriteKind
  | removeSimpleTau
  | markSkippable
  | abstractSelfLoop
  | abstractStronglyConnectedComponent
  | sequentializeChoiceGraph
  | flattenPartialOrder
  | mergeFrequency
  deriving DecidableEq, Repr

structure Step (Label : Type u) where
  kind : RewriteKind
  source : RawModel Label
  target : RawModel Label

/-- A rewrite has standing only when it preserves denotation. -/
def Sound {Label : Type u} (sem : Interpretation Label) (step : Step Label) : Prop :=
  sem.Equivalent step.target step.source

/-- Total normalizer over admitted models. -/
structure Normalizer (Label : Type u) where
  normalize : Model Label → Model Label
  steps : Model Label → List (Step Label)

namespace Normalizer

variable {Label : Type u}

/-- Global semantic obligation for normalization. -/
def PreservesLanguage (sem : Interpretation Label) (normalizer : Normalizer Label) : Prop :=
  ∀ model, sem.Equivalent (normalizer.normalize model).raw model.raw

/-- Canonicalization should be stable after one pass. -/
def Idempotent (normalizer : Normalizer Label) : Prop :=
  ∀ model, normalizer.normalize (normalizer.normalize model) = normalizer.normalize model

end Normalizer
end Normalization
end POWL

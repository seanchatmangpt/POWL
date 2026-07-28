import Mathlib

namespace POWL

/--
A closed lower bound and an optional closed upper bound.
`max = none` is the repository's unbounded maximum frequency.
-/
structure Frequency where
  min : Nat := 1
  max : Option Nat := some 1
  valid : ∀ n, max = some n → min ≤ n

namespace Frequency

/-- A repetition count is admitted exactly when it satisfies both frequency bounds. -/
def Allows (f : Frequency) (count : Nat) : Prop :=
  f.min ≤ count ∧ ∀ upper, f.max = some upper → count ≤ upper

/-- Mirrors `TaggedPOWL.is_skippable`. -/
def IsSkippable (f : Frequency) : Prop := f.min = 0

/-- Mirrors `TaggedPOWL.is_unbounded`. -/
def IsUnbounded (f : Frequency) : Prop := f.max = none

/-- Mirrors `TaggedPOWL.is_repeatable`. -/
def IsRepeatable (f : Frequency) : Prop :=
  f.max = none ∨ ∃ upper, f.max = some upper ∧ 1 < upper

@[simp] theorem allows_min (f : Frequency) : f.Allows f.min := by
  constructor
  · exact Nat.le_refl _
  · intro upper h
    exact f.valid upper h

@[simp] theorem not_skippable_of_positive (f : Frequency) (h : 0 < f.min) :
    ¬ f.IsSkippable := by
  intro hz
  unfold IsSkippable at hz
  omega

/-- Exact-once frequency, used by normalized internal nodes. -/
def once : Frequency where
  min := 1
  max := some 1
  valid := by
    intro n h
    cases h
    exact Nat.le_refl 1

/-- Optional, but not repeatable. -/
def optional : Frequency where
  min := 0
  max := some 1
  valid := by
    intro n _
    omega

/-- One-or-more repetition. -/
def oneOrMore : Frequency where
  min := 1
  max := none
  valid := by
    intro n h
    cases h

/-- Zero-or-more repetition. -/
def zeroOrMore : Frequency where
  min := 0
  max := none
  valid := by
    intro n h
    cases h

@[simp] theorem once_allows_iff (count : Nat) : once.Allows count ↔ count = 1 := by
  constructor
  · intro h
    have lower : 1 ≤ count := by
      simpa [Allows, once] using h.1
    have upper : count ≤ 1 := by
      simpa [once] using h.2 1 rfl
    exact Nat.le_antisymm upper lower
  · rintro rfl
    exact allows_min once

@[simp] theorem optional_allows_iff (count : Nat) : optional.Allows count ↔ count ≤ 1 := by
  constructor
  · intro h
    exact h.2 1 rfl
  · intro h
    exact ⟨Nat.zero_le _, fun upper hUpper => by cases hUpper; exact h⟩

end Frequency
end POWL

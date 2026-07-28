import Mathlib
import POWL.Foundation.Frequency

namespace POWL

abbrev Trace (α : Type u) := List α
abbrev Language (α : Type u) := Set (Trace α)

namespace Language

variable {α : Type u}

/-- Silent behavior. -/
def epsilon : Language α := {[]}

/-- One observable activity. -/
def atom (a : α) : Language α := {[a]}

/-- Nondeterministic choice. -/
def choice (languages : Set (Language α)) : Language α := ⋃₀ languages

/-- Sequential language composition. -/
def seq (left right : Language α) : Language α :=
  {w | ∃ u ∈ left, ∃ v ∈ right, w = u ++ v}

/-- Interleaving witness for concurrent traces. -/
inductive Interleaves : List α → List α → List α → Prop
  | nil : Interleaves [] [] []
  | left {a : α} {xs ys zs : List α} :
      Interleaves xs ys zs → Interleaves (a :: xs) ys (a :: zs)
  | right {a : α} {xs ys zs : List α} :
      Interleaves xs ys zs → Interleaves xs (a :: ys) (a :: zs)

/-- Parallel composition is all order-preserving interleavings. -/
def parallel (left right : Language α) : Language α :=
  {w | ∃ u ∈ left, ∃ v ∈ right, Interleaves u v w}

/-- Exact finite iteration. -/
def power (body : Language α) : Nat → Language α
  | 0 => epsilon
  | n + 1 => seq body (power body n)

/-- Kleene closure. -/
def star (body : Language α) : Language α := ⋃ n, power body n

/-- Frequency-restricted iteration. -/
def boundedPower (body : Language α) (frequency : Frequency) : Language α :=
  ⋃ n, ⋃ (_ : frequency.Allows n), power body n

@[simp] theorem mem_epsilon (w : Trace α) : w ∈ epsilon ↔ w = [] := by
  rfl

@[simp] theorem seq_epsilon_left (L : Language α) : seq epsilon L = L := by
  ext w
  simp [seq, epsilon]

@[simp] theorem seq_epsilon_right (L : Language α) : seq L epsilon = L := by
  ext w
  simp [seq, epsilon]

@[simp] theorem atom_ne_epsilon (a : α) : atom a ≠ epsilon := by
  intro h
  have : [a] ∈ (epsilon : Language α) := by
    rw [← h]
    simp [atom]
  simpa [epsilon] using this

end Language
end POWL

import POWL.Model
import POWL.Process.Discovery
import POWL.Repository.Coverage

namespace POWL.Examples

open POWL

/-- Observable activity fixture. -/
def approve : Activity String where
  label := some "Approve"
  organization := some "Finance"
  role := some "Approver"

/-- Silent activity fixture. -/
def tau : Activity String where
  label := none

example : approve.IsObservable := by
  exact ⟨"Approve", rfl⟩

example : tau.IsSilent := by
  rfl

example : Frequency.once.Allows 1 := by
  simp

example : Repository.coverage.length > 0 := by
  decide

end POWL.Examples

import POWL

open POWL

/-- Executable receipt that the formal repository surface elaborated. -/
def main : IO Unit := do
  IO.println s!"POWL formalization coverage entries: {Repository.coverage.length}"
  IO.println "State: ALIVE only after `lake build` completes."

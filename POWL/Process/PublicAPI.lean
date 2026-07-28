import POWL.Process.Conversion
import POWL.Process.Discovery
import POWL.Process.Visualization

namespace POWL

namespace PublicAPI

inductive Operation
  | importEventLog
  | importObjectCentricLog
  | discover
  | discoverFromPartialOrder
  | discoverFromDirectlyFollowsGraph
  | discoverObjectCentric
  | visualizePOWL
  | visualizeNet
  | convertToPetriNet
  | convertFromWorkflowNet
  | convertToBPMN
  deriving DecidableEq, Repr

structure Request (Payload : Type u) where
  operation : Operation
  payload : Payload
  parameters : Discovery.Parameters := {}

inductive Response (Label Artifact : Type u)
  | discovered (model : Model Label)
  | rendered (artifact : Artifact)
  | converted (artifact : Artifact)

inductive Error
  | importFailed (message : String)
  | discoveryRefused (reason : Discovery.Refusal)
  | conversionFailed (message : String)
  | visualizationFailed (message : String)
  deriving Repr

/-- Public router shared by library calls and Streamlit adapters. -/
structure Router (Payload Label Artifact : Type u) where
  route : Request Payload → Except Error (Response Label Artifact)

/-- A UI adapter may decode and render, but it cannot manufacture an admitted model. -/
structure UIAdapter (UIRequest Payload Artifact : Type u) where
  decode : UIRequest → Except String Payload
  render : Artifact → String

end PublicAPI
end POWL

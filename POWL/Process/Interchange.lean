import Lean.Data.Json
import POWL.Model

namespace POWL

namespace Interchange

/-- File-level metadata admitted by POWL JSON 1.0. -/
structure Metadata where
  name : Option String := none
  description : Option String := none
  creator : Option String := none
  createdAt : Option String := none
  toolName : Option String := none
  toolVersion : Option String := none
  deriving Repr

/-- Typed failure classes rather than stringly exceptions. -/
inductive ValidationError
  | invalidJson (message : String)
  | wrongFormat (found : Option String)
  | unsupportedVersion (found : Option String)
  | missingField (path : String)
  | unknownField (path field : String)
  | invalidFrequency (path : String)
  | invalidReference (path : String)
  | cyclicPartialOrder (path : String)
  | nonReducedPartialOrder (path : String)
  | disconnectedChoiceGraph (path : String)
  deriving Repr

/-- Parsed file retaining non-semantic metadata. -/
structure Document (Label : Type u) where
  format : String := "powl-json"
  version : String := "1.0"
  metadata : Metadata := {}
  model : Model Label

/-- Codec contract. Implementations may be Python, Lean, Rust, or generated. -/
structure Codec (Label : Type u) where
  encode : RawModel Label → Lean.Json
  decode : Lean.Json → Except ValidationError (RawModel Label)
  validate : RawModel Label → Except ValidationError (Model Label)

namespace Codec

variable {Label : Type u} [DecidableEq Label]

/-- Successful decode after encode must recover the same raw syntax. -/
def RoundTrips (codec : Codec Label) : Prop :=
  ∀ model, codec.decode (codec.encode model) = .ok model

/-- Validation must never silently alter the submitted raw model. -/
def ValidationIsIdentity (codec : Codec Label) : Prop :=
  ∀ raw admitted, codec.validate raw = .ok admitted → admitted.raw = raw

end Codec
end Interchange
end POWL

import POWL.Model

namespace POWL

namespace Visualization

structure Point where
  x : Int
  y : Int
  deriving DecidableEq, Repr

structure Box where
  origin : Point
  width : Nat
  height : Nat
  deriving DecidableEq, Repr

/-- Geometry is a projection; it does not own process semantics. -/
structure Layout (Node : Type u) where
  bounds : Node → Box
  zIndex : Node → Int := fun _ => 0

/-- Rendering obligations shared by POWL, net, DFG, process-tree, and BPMN views. -/
structure Renderer (Model Node Artifact : Type) where
  nodes : Model → List Node
  render : Model → Layout Node → Artifact
  visible : Artifact → Node → Prop
  complete : ∀ model layout node,
    node ∈ nodes model → visible (render model layout) node

/-- Resource presentation carried by pools and lanes. -/
structure ResourceAssignment (Node : Type u) where
  organization : Node → Option String
  role : Node → Option String
  pool : Node → Option String
  lane : Node → Option String

/-- Resource-aware rendering must not change the underlying node identity. -/
def ResourceStable {Node : Type u}
    (before after : ResourceAssignment Node) : Prop :=
  ∀ node,
    before.organization node = after.organization node ∧
    before.role node = after.role node

end Visualization
end POWL

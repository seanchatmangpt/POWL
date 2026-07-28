import Mathlib

namespace POWL.Repository

/-- Repository surfaces, not merely the POWL AST. -/
inductive Subsystem
  | publicApi
  | streamlitApplications
  | modelCore
  | graphAlgorithms
  | frequencyNormalization
  | objectCentricModel
  | eventLogs
  | totalOrderDiscovery
  | partialOrderDiscovery
  | dfgDiscovery
  | objectCentricDiscovery
  | cutsBaseCasesFallThroughs
  | filtering
  | jsonInterchange
  | petriNetConversion
  | bpmnConversion
  | processTreeConversion
  | visualization
  | poolsAndLanes
  | examples
  | tests
  | packaging
  | deployment
  deriving DecidableEq, Repr

structure CoverageEntry where
  source : String
  subsystem : Subsystem
  leanModule : String
  principalObligation : String
  deriving Repr

/-- Auditable map from the Python repository to formal modules and proof obligations. -/
def coverage : List CoverageEntry := [
  ⟨"powl/main.py", .publicApi, "POWL.Process.PublicAPI", "public routing returns typed results or typed refusals"⟩,
  ⟨"app.py; app_po_based_discovery.py", .streamlitApplications, "POWL.Process.PublicAPI", "UI projections cannot manufacture admitted models"⟩,
  ⟨"powl/objects/tagged_powl/**", .modelCore, "POWL.Model", "raw syntax is separated from admitted models"⟩,
  ⟨"powl/objects/BinaryRelation.py; powl/objects/utils/**", .graphAlgorithms, "POWL.Foundation.Relation", "reachability, acyclicity, closure, and reduction"⟩,
  ⟨"powl/objects/tagged_powl/builders.py; **/normalize", .frequencyNormalization, "POWL.Process.Normalization", "skip, repeat, tau, SCC, and flattening rewrites preserve language"⟩,
  ⟨"powl/objects/oc_powl.py", .objectCentricModel, "POWL.Process.EventLog", "object relation classifications are preserved recursively"⟩,
  ⟨"powl/main.py import_event_log; PM4Py/XES/CSV adapters", .eventLogs, "POWL.Process.EventLog", "event, lifecycle, case, timestamp, and object projections are explicit"⟩,
  ⟨"powl/discovery/total_order_based/**", .totalOrderDiscovery, "POWL.Process.Discovery", "recursive inductive mining is sound and decreasing"⟩,
  ⟨"powl/discovery/partial_order_based/**", .partialOrderDiscovery, "POWL.Process.EventLog", "partial-order traces remain acyclic and bounded"⟩,
  ⟨"powl/discovery/dfg_based/**", .dfgDiscovery, "POWL.Process.Discovery", "DFG projections preserve supported behavior"⟩,
  ⟨"powl/discovery/object_centric/**", .objectCentricDiscovery, "POWL.Process.Discovery", "object-centric projections preserve type relations"⟩,
  ⟨"powl/discovery/**/base_case; **/cuts; **/fall_through", .cutsBaseCasesFallThroughs, "POWL.Process.Discovery", "every recursive branch decreases or returns a typed refusal"⟩,
  ⟨"powl/general_utils/*filtering.py; powl/discovery/**/filtering.py", .filtering, "POWL.Process.Discovery", "at most one filter strategy is representable"⟩,
  ⟨"powl/io/powl_json.py", .jsonInterchange, "POWL.Process.Interchange", "decode/encode roundtrip and semantic validation"⟩,
  ⟨"powl/conversion/variants/to_petri_net.py; powl/conversion/to_powl/from_pn/**", .petriNetConversion, "POWL.Process.Conversion", "language equivalence"⟩,
  ⟨"powl/conversion/variants/to_bpmn*.py", .bpmnConversion, "POWL.Process.Conversion", "control flow and resource assignment preservation"⟩,
  ⟨"powl/conversion/to_powl/from_tree.py", .processTreeConversion, "POWL.Process.Conversion", "operator semantics preservation"⟩,
  ⟨"powl/visualization/**", .visualization, "POWL.Process.Visualization", "rendering is total over model nodes"⟩,
  ⟨"powl/visualization/bpmn/resource_utils/**", .poolsAndLanes, "POWL.Process.Visualization", "organization and role projections are stable"⟩,
  ⟨"examples/**", .examples, "POWL.Examples", "executable witnesses elaborate"⟩,
  ⟨"tests/**", .tests, "POWL.Examples", "negative and positive fixtures compile"⟩,
  ⟨"pyproject.toml; requirements.txt; packages.txt", .packaging, "lakefile.toml", "Lean and Python artifacts remain independently reproducible"⟩,
  ⟨"Dockerfile; .github/workflows/**", .deployment, ".github/workflows/lean.yml", "kernel build executes in CI"⟩
]

/-- Coverage as a finite proposition. -/
def Covers (subsystem : Subsystem) : Prop := subsystem ∈ coverage.map (·.subsystem)

/-- The manifest has a witness for every declared repository subsystem. -/
theorem coverage_complete (subsystem : Subsystem) : Covers subsystem := by
  cases subsystem <;> simp [Covers, coverage]

end POWL.Repository

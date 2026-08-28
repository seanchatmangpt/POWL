# POWL PaaS Semantic Resource Manifest

Generated from `ontology/ggen-runtime-capabilities.ttl` by ggen. The ontology is the semantic source for this manifest; Ash resources are the operational application source and AshR2RML manufactures R2RML/SHACL projections from those resources.

## Execution intent

- **Class:** `https://powl.dev/ontology/ggen-runtime#Intent`
- **Ash module:** `PowlPlatform.Intent`
- **Table:** `powl_intents`
- **Authority:** `CONSTRUCT_ONLY`
- **Meaning:** A constructed request for execution. Intent is deliberately non-actuating and carries no ambient DO authority.

## Process model

- **Class:** `https://powl.dev/ontology/ggen-runtime#ProcessModel`
- **Ash module:** `PowlPlatform.ProcessModel`
- **Table:** `powl_process_models`
- **Authority:** `CONSTRUCT_ONLY`
- **Meaning:** An admitted POWL model stored by the Ash control plane; Python POWL remains the semantic model implementation.

## Actuation or run receipt

- **Class:** `https://powl.dev/ontology/ggen-runtime#Receipt`
- **Ash module:** `PowlPlatform.Receipt`
- **Table:** `powl_receipts`
- **Authority:** `VERIFY_ONLY`
- **Meaning:** Evidence emitted by or derived from the POWL receipted runtime. A named receipt is not accepted as evidence without the bound subject and consequence digest.

## Workflow run

- **Class:** `https://powl.dev/ontology/ggen-runtime#WorkflowRun`
- **Ash module:** `PowlPlatform.WorkflowRun`
- **Table:** `powl_workflow_runs`
- **Authority:** `BRCE_BOUNDARY`
- **Meaning:** A run binding and standing for an exact admitted POWL subject.

## Authority fence

`CONSTRUCT_ONLY` objects never actuate. `BRCE_BOUNDARY` denotes the boundary at which POWL's `WorkflowRunner` requires an `ActuationReceipt`; it does not grant authority by itself. Public ontology alignment is descriptive and carries no ambient execution authority.

Generated output is a projection. Edit the ontology, Ash resource source, or template; never hand-edit this manifest or AshR2RML-generated TTL.

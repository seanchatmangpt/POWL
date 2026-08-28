# POWL GGEN Runtime Capabilities

Generated from `ontology/ggen-runtime-capabilities.ttl`.


## Bounded partial-order fanout

- **Surface:** partial-order|concurrency
- **Authority:** CONSTRUCT_ONLY
- **Meaning:** Bounded asynchronous fanout for partial orders while preserving predecessor barriers and stable step identity.


## Exact subject identity

- **Surface:** identity|subject|sha
- **Authority:** VERIFY_ONLY
- **Meaning:** Pins generated consequences to an exact repository subject identity.


## POWL process discovery

- **Surface:** discovery|bpmn|pnml
- **Authority:** CONSTRUCT_ONLY
- **Meaning:** Process discovery from event logs into POWL 2.0 models with BPMN and PNML export surfaces.


## Receipted workflow runtime

- **Surface:** runtime|receipt|replay
- **Authority:** BRCE_BOUNDARY
- **Meaning:** WorkflowRunner separates selection from actuation and requires observable activities to cross a receipt-producing actuator boundary.


## Typed workflow standing

- **Surface:** standing|evidence
- **Authority:** VERIFY_ONLY
- **Meaning:** Runtime distinguishes REFUSED, BLOCKED, BUILD_BROKEN, UNSUPPORTED and ALIVE without ambient authority.



Generated output is a projection. Edit the ontology or template, never the generated reference.

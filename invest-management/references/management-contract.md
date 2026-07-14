# Management artifact contract

Use `module="management"`, company scope, and a non-scenario artifact unless a finding explicitly differs by forecast scenario. Current suite 5.2 data contains:

- `qualitative_schema_version="2.1"`;
- `facts`: each has a unique fact ID, fact type, dated statement, and one or more checked claim IDs;
- `interpretations`: each has a unique interpretation ID, statement, input fact IDs, contrary fact IDs, and confidence;
- `commitment_assessments`: each binds a prior commitment fact to outcome facts and a supported status;
- optional `execution_driver_assessments`: each binds one or more existing revenue-owned growth-driver IDs, optional management-target IDs, checked supporting/contrary fact IDs, an execution status, and a conclusion;
- `red_flag_interpretation_ids` and `disconfirming_fact_ids` that reference existing nodes;
- `data_gaps` as explicit non-empty strings.

Claims target factual nodes, not interpretations. Orphan claim IDs, unclaimed facts, future-dated facts, unknown interpretation inputs, and duplicate IDs all block finalization. Interpretations must not smuggle a new allegation that is absent from their input facts.

Decision-makers, integrity events, governance, incentives, execution, and succession are expressed as `fact_type` values plus interpretations. Measured capital-allocation outcomes remain in `invest-distribution` and can be referenced as upstream evidence instead of recalculated here.

Execution status is one of `on_track`, `delayed`, `off_track`, `unproven`, or `data_gap`. The first three require checked supporting facts. Unknown driver, target, or fact IDs block finalization. Suite-5.0 qualitative schema 2.0 artifacts remain valid immutable records; new artifacts use 2.1.

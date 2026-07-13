# Management artifact contract

Use `module="management"`, company scope, and a non-scenario artifact unless a finding explicitly differs by forecast scenario. Schema `2.0` data contains:

- `qualitative_schema_version="2.0"`;
- `facts`: each has a unique fact ID, fact type, dated statement, and one or more checked claim IDs;
- `interpretations`: each has a unique interpretation ID, statement, input fact IDs, contrary fact IDs, and confidence;
- `commitment_assessments`: each binds a prior commitment fact to outcome facts and a supported status;
- `red_flag_interpretation_ids` and `disconfirming_fact_ids` that reference existing nodes;
- `data_gaps` as explicit non-empty strings.

Claims target factual nodes, not interpretations. Orphan claim IDs, unclaimed facts, future-dated facts, unknown interpretation inputs, and duplicate IDs all block finalization. Interpretations must not smuggle a new allegation that is absent from their input facts.

Decision-makers, integrity events, governance, incentives, execution, and succession are expressed as `fact_type` values plus interpretations. Measured capital-allocation outcomes remain in `invest-distribution` and can be referenced as upstream evidence instead of recalculated here.

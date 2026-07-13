# SOTP composition contract

Each part must be a segment-scoped `valuation` artifact for the same company and frozen information set. Select either one named method or the artifact's explicit weighted result. All selected parts must use the same `enterprise` or `equity` aggregation basis.

For each scenario:

```text
owned segment value = selected segment EV or equity value × ownership
company raw value = sum(owned segment values)
company equity value = enterprise-to-equity bridge(company raw value), or equity-level bridge(company raw value)
```

The bridge can include only explicitly registered current monetary balances such as central cash/debt not already allocated, non-operating assets, pension deficits, provisions, or holding-company discounts. Record signs directly; do not rely on a name to determine arithmetic.

Before adding an adjustment, prove it is not already included in a segment enterprise-to-equity bridge.

## Management revenue targets

All parts must carry the identical revenue reference, including the hashed management-target summary. The SOTP output copies that summary so the final artifact can answer whether a target was included, whether it is annual/run-rate/cumulative/ambiguous, its reporting-perimeter reconciliation, the scenario to which it was mapped, and whether the modeled revenue met the normalized threshold. A disclosed target with no comparable reporting perimeter remains visible as an unmodeled data gap; SOTP must not imply attainment from total segment revenue. SOTP never performs this comparison itself.

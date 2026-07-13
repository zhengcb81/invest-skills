# Comparability protocol

Before comparing a metric, verify:

1. same owning module and artifact schema;
2. same company or segment scope definition;
3. same fiscal period or explicit period mapping;
4. same low/base/high scenario identity;
5. same accounting definition, including gross/net, continuing operations, lease treatment, and cash-flow type;
6. same currency and scale, or separate source-linked FX and unit-scale normalization at the comparison information date;
7. same per-share versus total-value basis.

Do not rank missing values as zero. Preserve `not_available` and explain which owning module must be rerun.

Each metric contract records target and source definitions, explicit source periods for every company, dimension, time basis, total/per-share value basis, and whether alignment is exact or reconciled. Reconciled definitions require company-specific notes. Non-monetary ratios must not be FX converted.

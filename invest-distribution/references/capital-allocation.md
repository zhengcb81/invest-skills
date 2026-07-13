# Capital-allocation definitions

Define each input before calculating:

- dividends: cash distributed to common shareholders;
- repurchases: gross cash spent purchasing common shares;
- share issuance: cash raised from common issuance, excluding stock compensation unless separately modeled;
- internal reinvestment: explicitly defined operating reinvestment measure, not a residual label;
- acquisition spend: purchase consideration under a consistent cash/debt/share basis;
- impairment: source-linked impairment associated with prior acquisitions;
- share count: consistent basic or diluted weighted-average/end-period basis.

Useful measures include payout to net income, net repurchase cash, acquisition impairment to acquisition spend, internal reinvestment to net income, and share-count CAGR. When net income or another denominator is non-positive, report the ratio as not meaningful rather than forcing a percentage.

Historical flows must be `reported_fact` or formula-backed `derived_fact` parameters with exact checked evidence. Declare one share-count basis, such as diluted weighted-average ordinary shares, and use it consistently for the per-share history. `profit_retained_after_dividends` means net income less dividends for the measured period; it is not the balance-sheet retained-earnings account.

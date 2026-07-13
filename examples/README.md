# Executable examples

The examples use checked-in immutable revenue outputs and synthetic downstream assumptions. They demonstrate contracts and execution only; they are not company forecasts.

```powershell
$env:REVENUE_FORECAST_DIR = "C:\path\to\revenue-forecast"
python examples/run_financial_families.py
python examples/run_holding_company.py
```

`run_financial_families.py` executes operating-company, bank, insurer, REIT, and pre-revenue financial artifacts and sends each through a compatible valuation method. `run_holding_company.py` executes a two-segment financials → valuation → SOTP → frozen bundle graph.

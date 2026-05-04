# AI Accountant

Python utilities for retrieving and normalizing Solana on-chain activity (via the
Helius Enhanced API) into accounting-grade Pandas DataFrames. Financial values are
preserved as `Decimal` end-to-end.

## Install

```bash
pip install -e ".[dev]"
```

## Quick example

```python
from ai_accountant import SolanaDataFetcher, TransactionParser

fetcher = SolanaDataFetcher(api_key="<HELIUS_KEY>")
df = fetcher.fetch_transactions_dataframe("<WALLET>", max_pages=1)

# Or stream lazily for large wallets, with resumable cursor checkpoints:
parser = TransactionParser("<WALLET>")
for raw_tx in fetcher.iter_transactions(
    "<WALLET>", on_cursor_advance=lambda c: open("cursor", "w").write(c),
):
    row = parser.parse(raw_tx)
    ...
```

## Real wallet report

Preview the readable HTML report without an API key, using the existing
synthetic demo dataset:

```powershell
python examples\demo_html_report.py
```

Generate a readable HTML dashboard and a CSV export from real Helius data:

```powershell
$env:HELIUS_API_KEY="your-helius-key"
python examples\real_wallet_report.py --wallet "<WALLET>" --max-pages 2
```

Outputs are written to `reports/`:

- `ai_accountant_<wallet>_<timestamp>.html` - human-readable wallet report
- `ai_accountant_<wallet>_<timestamp>_transactions.csv` - flat transaction export

Use `--max-pages 0` to fetch all available Helius pages. The report uses real
on-chain activity, but USD valuation, off-chain cost basis, exchange imports,
and legal citations still need dedicated integrations before it is a final tax
or accounting report.

## Layout

- `src/ai_accountant/` — `client`, `parser`, `transport`, `addresses`, `dataframe`, `exceptions`
- `examples/` — illustrative scaffolds (audit pipeline, legal grounding); not part of the public API
- `docs/superpowers/specs/` — design documents
- `tests/` — `pytest` suite

## Development

```bash
pytest                    # tests
ruff check .              # lint
ruff format .             # format
```

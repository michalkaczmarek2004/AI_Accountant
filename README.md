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

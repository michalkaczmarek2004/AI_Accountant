# AI Accountant for US Crypto Taxes

AI Accountant is a local Solana tax review prototype built for the Solana Colosseum review workflow. It turns Solana wallet activity into a CPA-ready draft tax review workflow: transaction classification, taxable-event detection, missing cost basis review, tax estimate assumptions, tax-loss harvesting review, audit trail, and exportable tax records.

This is not a tax filing product and it does not provide tax advice. It prepares a draft package for taxpayer or CPA review.

## What It Does

- Parses Solana wallet activity into accounting-oriented transaction records.
- Classifies likely US crypto tax categories such as buys, sales, swaps, staking rewards, airdrops, NFT mint/sale, self-transfers, failed transactions, and DeFi/wrapped-token review items.
- Highlights AI Accountant findings:
  - taxable events detected
  - possible self-transfer
  - missing basis issues
  - ordinary income events
  - estimated federal tax
  - CPA package readiness
- Shows Solana-specific patterns:
  - Jupiter swaps
  - staking rewards
  - SPL token activity
  - NFTs
  - wSOL / bridge review
  - fees in SOL
  - transaction signatures for audit trail
- Provides a traceable federal tax estimate with assumptions and disclaimers.
- Shows tax planning opportunities, including a SAMO loss review with a visible savings breakdown.
- Exports a CPA-ready CSV with tax classification fields, cost basis, proceeds, gain/loss, holding period, FMV, fees, review status, confidence, and audit context.

## Product Positioning

The product should be presented as:

> AI Accountant for US Crypto Taxes

Core value:

> Classify Solana transactions, detect taxable events, find missing cost basis, and generate a CPA-ready review package.

Avoid presenting it as a portfolio tracker or as final tax filing software. The right framing is:

> CPA-ready draft package, not final tax filing.

## Requirements

- Python 3.10+
- pip
- PowerShell on Windows, or any shell that can run Python
- Optional: Helius API key for real wallet fetches

## Local Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,dashboard]"
```

If you do not want to create a virtual environment, you can run the install command directly in your active Python environment:

```powershell
python -m pip install -e ".[dev,dashboard]"
```

## Two Run Modes

The dashboard ships in two run modes from the same codebase:

- **Port 8770 – presentation version.** Includes the prepared 2025 US taxpayer story, a `Run US Tax Review` CTA, and a `Reset Presentation State` button. Use for live walkthroughs and demos.
- **Port 8765 – judge-review version.** A normal usable instance with no demo-only controls (no `Run US Tax Review` CTA, no reset, no presenter chrome). Use this for hands-on inspection.

Both versions share the same Tax Assistant, Tax Files workflow, and Wallet pages, and both expose the navbar logo + `AI Accountant` brand.

### Judge-Review Version (Port 8765)

Start the judge-review version (no demo controls, normal usable app):

```powershell
python -m ai_accountant.dashboard.cli serve --review-mode --host 127.0.0.1 --api-key demo-not-used --cache-dir .ai_accountant\wallets
```

Open:

```text
http://127.0.0.1:8765
```

From the landing page you can:

- Paste any Solana wallet address to fetch its activity (real fetches require a Helius API key — see [Run With a Real Wallet](#run-with-a-real-wallet)).
- Click `Open Tax Files` to create or open a tax file and link wallets.
- Click `Wallets` in the navbar to see the cached wallets list.

Use a real Helius API key in place of `demo-not-used` for live wallet fetches.

### Presentation Version (Port 8770)

Seed the local presentation dataset:

```powershell
python -m ai_accountant.dashboard.cli demo --cache-dir .ai_accountant\wallets
```

Start the presentation dashboard:

```powershell
python -m ai_accountant.dashboard.cli serve --host 127.0.0.1 --port 8770 --api-key demo-not-used --cache-dir .ai_accountant\wallets
```

Open:

```text
http://127.0.0.1:8770
```

Then click:

```text
Run US Tax Review
```

The main Tax File is:

```text
2025 US Crypto Tax Review
```

Direct URL:

```text
http://127.0.0.1:8770/tax-files/2025-us-crypto-tax-review
```

## Recommended 3-5 Minute Review Flow

1. Open the landing page.
2. Show the headline: `AI Accountant for US Crypto Taxes`.
3. Click `Run US Tax Review`.
4. Show `AI Accountant Findings`.
5. Show `Solana Patterns Detected`.
6. Click `Confirm: Transfer from my own wallet`.
7. Explain that the user confirmation is added to the audit trail.
8. Open `Unified Tax Assistant`.
9. Show the estimated federal tax assumptions.
10. Show the SAMO tax-loss harvesting breakdown.
11. Show the CPA-ready export section.
12. End with: `From Solana wallet chaos to CPA-ready tax review in minutes.`

## Sample Tax Review Dataset

The presenter dataset is:

```text
2025 US taxpayer story
```

It includes examples for:

- USD funding / acquisition support record
- SOL purchase
- crypto-to-crypto swap
- stablecoin swap
- staking reward
- airdrop
- NFT mint
- NFT sale
- self-transfer between owned wallets
- wSOL / bridge-style review
- LP / DeFi review
- failed transaction fee
- missing historical price
- missing cost basis
- duplicate exchange-support record
- SAMO unrealized loss candidate for tax-loss harvesting review

## Reset the Tax Review

Use the in-app button:

```text
Reset Presentation State
```

Or reseed from the command line:

```powershell
python -m ai_accountant.dashboard.cli demo --cache-dir .ai_accountant\wallets
```

Resetting restores the self-transfer review item so the review flow can be repeated cleanly.

## Run With a Real Wallet

Set your Helius API key:

```powershell
$env:HELIUS_API_KEY="your-helius-api-key"
```

Fetch a wallet into the local cache:

```powershell
python -m ai_accountant.dashboard.cli fetch <SOLANA_WALLET_ADDRESS> --max-pages 5 --cache-dir .ai_accountant\wallets
```

Start the dashboard:

```powershell
python -m ai_accountant.dashboard.cli serve --host 127.0.0.1 --port 8770 --api-key $env:HELIUS_API_KEY --cache-dir .ai_accountant\wallets
```

Open:

```text
http://127.0.0.1:8770
```

For full wallet history, use:

```powershell
python -m ai_accountant.dashboard.cli fetch <SOLANA_WALLET_ADDRESS> --max-pages 0 --cache-dir .ai_accountant\wallets
```

## CLI Shortcuts

After installing the package, the `dashboard` script is also available:

```powershell
dashboard demo --cache-dir .ai_accountant\wallets
dashboard serve --host 127.0.0.1 --port 8770 --api-key demo-not-used --cache-dir .ai_accountant\wallets
dashboard fetch <SOLANA_WALLET_ADDRESS> --api-key $env:HELIUS_API_KEY --cache-dir .ai_accountant\wallets
```

The module form is usually safer when debugging environment issues:

```powershell
python -m ai_accountant.dashboard.cli --help
```

## Key Screens

- Landing page: product positioning and review CTA.
- Tax File: AI Accountant Findings, Solana Patterns Detected, review queue, tax classification, cost basis, audit trail, and export package.
- Unified Tax Assistant: US tax notes, KPI summary, reporting vs planning, estimate assumptions, tax optimization breakdown, and export.
- CPA-ready export: CSV package for review, not automatic filing.

## Tax Estimate Notes

The federal estimate is traceable but still a draft. It is based on:

- verified realized gains
- ordinary income
- selected federal rate assumption
- review-status adjustments
- missing basis exposure
- state tax excluded / not configured

The UI intentionally labels estimates as draft review outputs. A taxpayer or CPA must review final cost basis, FMV, tax treatment, and filing forms.

## Run Tests

```powershell
python -m pytest -q
```

Optional lint:

```powershell
python -m ruff check .
python -m ruff format .
```

## Troubleshooting

### Missing Flask or Jinja

Install the dashboard extra:

```powershell
python -m pip install -e ".[dashboard]"
```

For development:

```powershell
python -m pip install -e ".[dev,dashboard]"
```

### Missing Helius API Key

The server command requires an API key argument or `HELIUS_API_KEY`, even when you are using seeded review data. For the local review workflow, this is fine:

```powershell
python -m ai_accountant.dashboard.cli serve --api-key demo-not-used
```

For real wallet fetches, use a real key:

```powershell
$env:HELIUS_API_KEY="your-helius-api-key"
```

### Port Already in Use

Use another port:

```powershell
python -m ai_accountant.dashboard.cli serve --host 127.0.0.1 --port 8771 --api-key demo-not-used --cache-dir .ai_accountant\wallets
```

Then open:

```text
http://127.0.0.1:8771
```

### Review Looks Already Resolved

Click:

```text
Reset Presentation State
```

Or run:

```powershell
python -m ai_accountant.dashboard.cli demo --cache-dir .ai_accountant\wallets
```

## Project Layout

- `src/ai_accountant/` - Solana client, parser, DataFrame utilities, reports, and tax assistant logic.
- `src/ai_accountant/dashboard/` - local Flask dashboard, sample data, Tax File workflow, templates, and static assets.
- `tests/` - pytest suite for parser, dashboard, Tax File, exports, routes, and review flow.
- `docs/superpowers/` - design notes and implementation plans.

## Disclaimer

This project is a prototype for crypto tax review workflows. It is not financial, legal, or tax advice. It does not file tax returns. Always review outputs with a qualified tax professional before relying on them for tax reporting or planning.

# Sentinel Module — Sprint 1: Sentinel Core

**Date:** 2026-05-03  
**Status:** Approved  
**Sprint:** 1 of 3  

---

## 1. Context & Goal

The AI Accountant ecosystem (`ai_accountant`) is a passive data-retrieval and normalization library built around `SolanaDataFetcher`. Transactions are fetched on demand via the Helius Enhanced API and returned as accounting-grade Pandas DataFrames.

Sprint 1 adds the **Sentinel Core** — a real-time monitoring layer that receives Helius webhook events, normalizes them using the existing transaction-parsing logic, scores them against configurable anomaly rules, and dispatches alerts to registered handlers. The goal is a working, fully-tested backbone that Sprints 2 and 3 can extend without structural changes.

---

## 2. Scope

### In scope

- Helius Enhanced Webhook POST receiver (`/webhook`)
- Webhook authentication — header comparison and HMAC-SHA256
- Event normalization from raw Helius payload to `WatchedEvent`
- Five rule-based anomaly detection rules plus one opt-in rule (`NEW_COUNTERPARTY`)
- Pluggable alert handler protocol (`AlertHandler` ABC)
- Two built-in alert handlers: `LoggingAlertHandler`, `FileAlertHandler`
- Local config (TOML on Python ≥ 3.11, JSON on Python ≥ 3.10) with validation and env-var secret resolution
- In-process alert deduplication per `Dispatcher` instance
- `GET /healthz` health check endpoint
- Full test coverage via Flask `test_client()` — no live server required

### Explicitly out of scope

- Price oracles, tax-loss harvesting detection — **Sprint 2**
- Legal RAG cross-reference, Wallet Health scoring — **Sprint 3**
- Solana Actions / Blinks recommendations — **Sprint 3**
- Production Telegram, Discord, Web Push integrations — **Sprint 2/3**
- Persistent deduplication state across process restarts — **Sprint 2**
- Extraction of `_build_transaction_row` into a public utility — **pre-Sprint-2 task**

---

## 3. Package Layout

```
src/ai_accountant/
    __init__.py                  # unchanged; does NOT import sentinel
    solana_data_fetcher.py       # unchanged
    sentinel/
        __init__.py              # re-exports: create_app, load_config, AlertHandler
        app.py                   # create_app(config, handlers) -> Flask
        auth.py                  # authenticate_request(request, config) -> bool
        config.py                # SentinelConfig + nested dataclasses + loader
        models.py                # WatchedEvent, RuleResult, AnomalyScore, AlertPayload
        normalizer.py            # normalize(payload, wallet_address) -> list[WatchedEvent]
        engine.py                # score_event(config, event) -> AnomalyScore
        dispatcher.py            # AlertHandler ABC, Dispatcher, built-in handlers

tests/
    conftest.py                  # shared fixtures
    test_sentinel_config.py
    test_sentinel_auth.py
    test_sentinel_normalizer.py
    test_sentinel_engine.py
    test_sentinel_dispatcher.py
    test_sentinel_integration.py

sentinel_config.example.toml    # annotated reference config (project root)
```

Flask and all sentinel imports are confined to `sentinel/`. The top-level `ai_accountant/__init__.py` is not modified. Existing users who do not install Flask are unaffected.

---

## 4. End-to-End Data Flow

```
Helius POST /webhook
  │
  ├─ auth.py: authenticate_request()
  │    ├─ auth disabled → pass
  │    ├─ valid secret / valid HMAC → pass
  │    └─ invalid or missing → 401 Unauthorized  [fail closed]
  │
  ├─ app.py: parse JSON body
  │    └─ non-JSON body → 400 Bad Request
  │
  ├─ normalizer.py: normalize(body, wallet_address)
  │    ├─ invalid wallet_address → 400 Bad Request
  │    ├─ _extract_transactions(body)  [handles both Helius payload shapes]
  │    └─ per transaction:
  │         ├─ malformed → skip; accumulate skipped_count + skipped_signatures
  │         └─ success → WatchedEvent (event_id, direction, Decimal fields)
  │    └─ if skipped_count > 0 → logger.warning(skipped_count, skipped_signatures)
  │
  ├─ for each WatchedEvent:
  │    ├─ wallet_address not in config.monitored_wallets → skip silently
  │    ├─ engine.py: score_event(config, event) → AnomalyScore
  │    └─ score < config.alerts.min_alert_score → skip silently
  │         └─ Dispatcher.dispatch(AlertPayload):
  │              ├─ deduplication: (event_id, frozenset(triggered_rules)) in _seen → skip
  │              └─ per handler:
  │                   ├─ handler.send(payload) → success
  │                   └─ exception → logger.error(handler.name, event_id), continue
  │
  └─ return 200 OK

GET /healthz → 200 {"status": "ok"}  [no external calls, no wallet state]
```

---

## 5. Data Models (`models.py`)

All models are stdlib-only frozen dataclasses. No external dependencies.

### `WatchedEvent`

Normalized, wallet-perspective view of one on-chain event. Field names and types mirror `SolanaDataFetcher.DATAFRAME_COLUMNS` so Sprint 2/3 code can treat webhook events and polled rows uniformly.

```
WatchedEvent (frozen dataclass)
  event_id           str        deterministic SHA-256 hash — see derivation
  signature          str
  wallet_address     str
  slot               int | None
  timestamp_unix     int | None
  timestamp          str | None  "YYYY-MM-DD HH:MM:SS" UTC, same format as DataFrame
  transaction_type   str | None
  source             str | None
  fee_sol            Decimal
  fee_paid_by_wallet bool
  fee_payer          str | None
  native_in_sol      Decimal
  native_out_sol     Decimal
  native_net_sol     Decimal
  direction          str        "in" | "out" | "mixed" | "neutral"
  movements_in       tuple[dict, ...]   same movement schema as SolanaDataFetcher
  movements_out      tuple[dict, ...]
  status             str        "succeeded" | "failed"
  raw                dict       original Helius payload — extension point
```

**`event_id` derivation:**  
SHA-256 of `"<signature>|<wallet_address>|<transaction_type or ''>|<native_net_sol>|<source or ''>"`, hex-encoded. Deterministic across identical inputs; idempotency-safe for future cross-process deduplication.

**`direction` derivation:**

| Condition | `direction` |
|---|---|
| `native_in_sol > 0` and `native_out_sol == 0` | `"in"` |
| `native_out_sol > 0` and `native_in_sol == 0` | `"out"` |
| Both > 0 | `"mixed"` |
| Both == 0 | `"neutral"` |

`movements_in` and `movements_out` are `tuple` (not `list`) to preserve the frozen dataclass invariant.

### `RuleResult`

Internal result from a single anomaly rule. Never exposed directly to alert handlers.

```
RuleResult (frozen dataclass)
  rule_id      str        e.g. "LARGE_SOL_TRANSFER"
  score_delta  int        contribution to total; 0 if rule did not trigger
  reason       str | None human-readable explanation when triggered;
                          e.g. "Outgoing 5.2 SOL exceeded threshold 2.0 SOL"
```

### `AnomalyScore`

Output of the engine for one event.

```
AnomalyScore (frozen dataclass)
  score            int         0–100, clamped sum of triggered rule deltas
  triggered_rules  list[str]   rule_ids of all fired rules
  reasons          list[str]   non-None RuleResult.reason values from triggered rules,
                               same order as triggered_rules; rules that return
                               reason=None are excluded from this list
  risk_level       str         "low" | "medium" | "high" | "critical"
```

Risk bands:

| Score range | `risk_level` |
|---|---|
| 0–24 | `"low"` |
| 25–49 | `"medium"` |
| 50–79 | `"high"` |
| 80–100 | `"critical"` |

### `AlertPayload`

Delivered to every `AlertHandler.send()`.

```
AlertPayload (frozen dataclass)
  event                  WatchedEvent
  score                  AnomalyScore
  severity               str         "INFO" | "WARNING" | "HIGH" | "CRITICAL"
  summary                str         auto-generated one-liner
  recommended_action_url str | None  None in Sprint 1; Sprint 3 populates with Blink URL
  # extension point: tax_impact (Sprint 2), legal_flags (Sprint 3)
```

**`severity` derivation from `risk_level`:**

| `risk_level` | `severity` |
|---|---|
| `"low"` | `"INFO"` |
| `"medium"` | `"WARNING"` |
| `"high"` | `"HIGH"` |
| `"critical"` | `"CRITICAL"` |

`risk_level` and `severity` are separate fields so the engine's technical classification and the user-facing display label can diverge in Sprint 3 without a breaking change.

**`summary` format** (auto-generated by `_build_summary`):
```
[CRITICAL] SWAP | 5.2 SOL out | rules=LARGE_SOL_TRANSFER,KNOWN_BAD_PROGRAM
```

---

## 6. Authentication (`auth.py`)

Two modes are supported. The mode is selected by `config.auth.type`.

### Header mode (`type = "header"`)

The `Authorization` header value is compared directly against the configured secret using `hmac.compare_digest` to prevent timing attacks.

### HMAC mode (`type = "hmac"`)

The `Authorization` header contains `HMAC-SHA256(raw_request_body, secret)` in hex. The server recomputes the digest from `request.data` and compares with `hmac.compare_digest`.

### Fail-closed invariants

| Condition | Outcome |
|---|---|
| `auth.enabled = True`, `Authorization` header absent | 401 |
| `auth.enabled = True`, header present but comparison fails | 401 |
| `auth.enabled = True`, `secret = ""` at startup | `ValueError` before Flask starts |
| `environment = "production"`, `auth.enabled = False` | `ValueError` before Flask starts |
| `auth.enabled = False` | Header ignored; all requests pass |

There is no "warn but pass" mode. `/healthz` is exempt from authentication in `before_request`.

---

## 7. Normalization (`normalizer.py`)

### Helius payload shapes

`_extract_transactions(payload: dict | list) -> list[dict]` handles both Helius formats:

- **Array format** (current): `[{...tx...}, ...]`
- **Envelope format** (older): `{"type": "TRANSACTION", "transactions": [...]}`

### Lazy fetcher

The normalizer reuses `SolanaDataFetcher._build_transaction_row()` for lamports→SOL conversion, Decimal arithmetic, and wallet-movement parsing. The fetcher is constructed lazily via `_get_fetcher()` on first call — not at module import time:

```python
_fetcher: SolanaDataFetcher | None = None

def _get_fetcher() -> SolanaDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = SolanaDataFetcher(api_key="sentinel-internal", session=_NoOpSession())
    return _fetcher
```

> **Tech debt (pre-Sprint-2):** `_build_transaction_row` is a private method. A follow-up
> task should extract the shared parsing logic into a public
> `parse_transaction(wallet_address, raw_tx) -> dict` function in `solana_data_fetcher.py`
> so the sentinel stops relying on a private API.

### Error isolation

If `_build_transaction_row` raises `HeliusAPIError` for a transaction, that transaction is skipped. After the full batch is processed, a single `logger.warning` records `skipped_count` and the list of `skipped_signatures` if any were skipped. The webhook endpoint still returns 200 — a parse error on one transaction must not cause Helius to retry the entire batch.

### `normalize` signature

```python
def normalize(
    payload: dict | list,
    monitored_wallets: frozenset[str],
) -> list[WatchedEvent]:
```

The function emits one `WatchedEvent` per `(transaction, wallet_address)` pair where `wallet_address` is in `monitored_wallets` **and** the wallet actually appears in that transaction's movements (inbound or outbound). Wallets that appear in `monitored_wallets` but have no movements in a given transaction produce no `WatchedEvent` for that transaction — this is not an error.

Wallets that appear in the transaction but are **not** in `monitored_wallets` are silently ignored and produce no `WatchedEvent`. Unknown wallets are never an error condition.

**One transaction → multiple events:** A single transaction involving two monitored wallets produces two `WatchedEvent` objects with different `wallet_address` values and different `event_id` hashes. Each wallet's perspective is scored and alerted independently. This is the expected behavior when e.g. a swap touches two wallets both under surveillance.

Each `wallet_address` in `monitored_wallets` is pre-validated via `SolanaDataFetcher.validate_address` at `load_config` time, so no per-call re-validation is needed inside `normalize`.

---

## 8. Anomaly Engine (`engine.py`)

### Rule protocol

Each rule is a standalone pure function:

```python
def rule_<name>(config: SentinelConfig, event: WatchedEvent) -> RuleResult
```

A rule always returns a `RuleResult`. When not triggered, `score_delta = 0` and `reason = None`.

### Sprint 1 rules

| Rule ID | Default weight | Trigger | What is examined |
|---|---|---|---|
| `LARGE_SOL_TRANSFER` | 40 | `native_out_sol > thresholds.large_transfer_sol` | `WatchedEvent` fields |
| `KNOWN_BAD_PROGRAM` | 60 | Any address in `raw["accountData"][*].account` or any movement counterparty is in `rules.blacklisted_programs` | `event.raw` + movements |
| `MASS_TOKEN_DRAIN` | 50 | Distinct **mints** in `movements_out` > `thresholds.mass_drain_token_count` | `movements_out` mint field |
| `FEE_SPIKE` | 20 | `fee_sol > thresholds.max_fee_sol` | `WatchedEvent` fields |
| `FAILED_HIGH_FEE` | 15 | `status == "failed"` AND `fee_paid_by_wallet` AND `fee_sol > thresholds.failed_tx_fee_sol` | `WatchedEvent` fields |
| `NEW_COUNTERPARTY` | 10 | Counterparty not seen in current process run (opt-in; disabled by default) | `movements_in` + `movements_out` |

**`MASS_TOKEN_DRAIN`** counts `{m["mint"] for m in movements_out if m.get("asset_type") == "token"}`. Repeated movements of the same mint do not inflate the count.

**`NEW_COUNTERPARTY`** maintains an in-memory `set[str]` of seen counterparties scoped to the process lifetime. Disabled by default (`check_new_counterparty = False`) because the state is lost on restart. Sprint 2 backs this with a persistent store.

**`KNOWN_BAD_PROGRAM`** checks only the addresses in `config.rules.blacklisted_programs`. The default is `frozenset()` — users populate it manually. No built-in threat-intel feed in Sprint 1.

### `score_event`

```python
def score_event(config: SentinelConfig, event: WatchedEvent) -> AnomalyScore:
    results = [rule_fn(config, event) for rule_fn in _enabled_rules(config)]
    triggered = [r for r in results if r.score_delta > 0]
    total = min(sum(r.score_delta for r in triggered), 100)
    return AnomalyScore(
        score=total,
        triggered_rules=[r.rule_id for r in triggered],
        reasons=[r.reason for r in triggered if r.reason is not None],
        risk_level=_risk_level(total),
    )
```

### Rule weight constraints

Rule weights are hardcoded in Sprint 1. The design constrains all weights to `[0, 100]` in preparation for future configurability. If weights become user-configurable in a later sprint, `load_config` must enforce this range.

### Scoring calibration rationale

`KNOWN_BAD_PROGRAM` alone (60) reaches `"high"`. Combined with any second rule it hits `"critical"`. `LARGE_SOL_TRANSFER` alone (40) lands at `"high"`. This is intentional: drainer interactions must escalate immediately; large transfers warrant high alert but not automatic critical.

---

## 9. Alert Dispatcher (`dispatcher.py`)

### `AlertHandler` ABC

```python
class AlertHandler(ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def send(self, payload: AlertPayload) -> None: ...
```

This is the only interface Sprint 2/3 integrations need to implement. No stub classes for Telegram, Discord, or Web Push exist in `dispatcher.py` — they are documented below as extension points only.

### `Dispatcher`

```python
class Dispatcher:
    def __init__(self, handlers: list[AlertHandler]) -> None:
        self._handlers = handlers
        self._seen: set[tuple[str, frozenset[str]]] = set()

    def dispatch(self, payload: AlertPayload) -> None:
        key = (payload.event.event_id, frozenset(payload.score.triggered_rules))
        if key in self._seen:
            logger.debug("Duplicate skipped: event_id=%s", payload.event.event_id)
            return
        self._seen.add(key)
        for handler in self._handlers:
            try:
                handler.send(payload)
            except Exception as exc:
                logger.error(
                    "AlertHandler '%s' failed for event_id=%s: %s",
                    handler.name, payload.event.event_id, exc,
                    exc_info=True,
                )
```

Deduplication is per `Dispatcher` instance — `_seen` is not shared across instances. A new `Dispatcher` starts with an empty `_seen` set. Deduplication does not persist across process restarts (Sprint 2).

`create_app` constructs the `Dispatcher` internally from the supplied `handlers` list.

### `LoggingAlertHandler`

Writes one structured log record per alert at `WARNING` or `CRITICAL` (mapped from `severity`). Fields logged: `event_id`, `wallet_address`, `score`, `severity`, `triggered_rules`, `summary`. No external dependencies.

### `FileAlertHandler`

Appends one JSON line per alert to `config.alerts.file_alert_path`. `Decimal` values are serialized as strings (not floats) to preserve accounting precision. If the write fails (disk full, permission error, etc.), the error is logged and the exception is swallowed. File write failures are strictly non-fatal — the webhook request is never failed due to a handler I/O error.

### Extension points for Sprint 2/3 (documentation only — no code in `dispatcher.py`)

- `TelegramAlertHandler` — Telegram Bot API `POST /sendMessage`
- `DiscordAlertHandler` — Discord Incoming Webhook
- `WebPushAlertHandler` — Web Push with VAPID keys

---

## 10. Config Schema (`config.py`)

### Dataclass hierarchy

All dataclasses are `frozen=True`. Safe defaults allow tests to override only what they care about.

```
SentinelConfig
├── environment: str                    "local" | "test" | "production"
├── monitored_wallets: frozenset[str]   required; validated at load time
│
├── AuthConfig
│   ├── enabled: bool = True
│   ├── type: str = "header"            "header" | "hmac"
│   └── secret: str = ""               supports "env:VAR_NAME" indirection
│
├── ThresholdConfig
│   ├── large_transfer_sol: Decimal = Decimal("10.0")
│   ├── max_fee_sol: Decimal = Decimal("0.01")
│   ├── failed_tx_fee_sol: Decimal = Decimal("0.001")
│   └── mass_drain_token_count: int = 3
│
├── RuleConfig
│   ├── check_large_sol_transfer: bool = True
│   ├── check_known_bad_program: bool = True
│   ├── check_mass_token_drain: bool = True
│   ├── check_fee_spike: bool = True
│   ├── check_failed_high_fee: bool = True
│   ├── check_new_counterparty: bool = False     opt-in; in-memory state only
│   └── blacklisted_programs: frozenset[str] = frozenset()
│
└── AlertConfig
    ├── min_alert_score: int = 50
    ├── enabled_handlers: tuple[str, ...] = ("logging",)
    │                                        valid values: "logging", "file"
    │                                        "file" activates FileAlertHandler
    │                                        this is the single control point for outputs
    ├── log_level: str = "WARNING"
    └── file_alert_path: str = "sentinel_alerts.jsonl"
                               read and used ONLY when "file" is in enabled_handlers
                               ignored entirely otherwise
```

### Validation rules

All checks run in `_validate_config`, called by `load_config` before `create_app` is invoked. Every failure raises `ValueError` with a descriptive message.

| Check | Failure condition |
|---|---|
| Non-empty wallets | `monitored_wallets` is empty |
| Valid wallet addresses | Any entry fails `SolanaDataFetcher.validate_address` |
| Auth secret required | `auth.enabled = True` and resolved secret is empty |
| Production requires auth | `environment = "production"` and `auth.enabled = False` |
| Valid auth type | `auth.type` not in `{"header", "hmac"}` |
| Non-negative thresholds | `large_transfer_sol`, `max_fee_sol`, or `failed_tx_fee_sol` < 0 |
| Valid score range | `alerts.min_alert_score` outside `[0, 100]` |
| Positive drain count | `thresholds.mass_drain_token_count < 1` |
| Valid environment | `environment` not in `{"local", "test", "production"}` |
| No unknown keys | Any key in the config file not present in the known schema |

### Secret resolution

If `auth.secret` starts with `"env:"`, `os.environ[var_name]` is read. If the variable is unset or empty, `ValueError` is raised immediately. Bare string values are used as-is.

### File format support

| Extension | Parser | Python version requirement |
|---|---|---|
| `.toml` | `tomllib` (stdlib) | ≥ 3.11 |
| `.json` | `json` (stdlib) | ≥ 3.10 |

On Python 3.10 with a `.toml` config file, the error message directs the user to upgrade to 3.11 or switch to JSON.

---

## 11. Flask App Factory (`app.py`)

```python
def create_app(config: SentinelConfig, handlers: list[AlertHandler]) -> Flask:
```

This is the single entry point. No global `Flask` app object exists anywhere in the sentinel package.

```python
def create_app(config: SentinelConfig, handlers: list[AlertHandler]) -> Flask:
    app = Flask(__name__)
    dispatcher = Dispatcher(handlers)
    app.extensions["sentinel_dispatcher"] = dispatcher
    app.extensions["sentinel_config"] = config

    @app.before_request
    def verify_auth():
        if request.path == "/healthz":
            return
        if not authenticate_request(request, config):
            abort(401)

    @app.post("/webhook")
    def webhook():
        if not request.is_json:
            abort(400)
        body = request.get_json(silent=True)
        if body is None:
            abort(400)
        events = normalize(body, config.monitored_wallets)
        for event in events:
            score = score_event(config, event)
            if score.score < config.alerts.min_alert_score:
                continue
            payload = _build_alert_payload(event, score)
            dispatcher.dispatch(payload)
        return "", 200

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

**`/healthz`** never calls Helius, never reads wallet state, never touches the dispatcher. It is dependency-free by design. It is also exempt from `before_request` authentication.

**Production deployment:** `waitress.serve(create_app(config, handlers), host="0.0.0.0", port=8080)` — one line; Werkzeug's dev server is only for local use.

---

## 12. Testing Strategy

### Shared fixtures (`conftest.py`)

| Fixture | What it provides |
|---|---|
| `make_config(**overrides)` | `SentinelConfig` with `environment="test"`, `auth.enabled=False`, `min_alert_score=0`, one valid wallet. Overrides applied at leaf level. |
| `make_event(**overrides)` | `WatchedEvent` with all-zero financial fields, `status="succeeded"`, `direction="neutral"` |
| `make_helius_payload(txs)` | Minimal valid Helius array-format body wrapping a list of tx dicts |
| `FakeAlertHandler` | Captures every `AlertPayload` in `self.received: list[AlertPayload]` |
| `test_app(config, handlers)` | Returns `create_app(config, handlers).test_client()` |

### `test_sentinel_config.py`

| Test | What it asserts |
|---|---|
| `test_valid_config_loads` | Well-formed config produces a `SentinelConfig` |
| `test_empty_wallets_raises` | `monitored_wallets = []` → `ValueError` |
| `test_invalid_wallet_address_raises` | Bad Base58 address → `ValueError` |
| `test_negative_large_transfer_raises` | `large_transfer_sol = -1` → `ValueError` |
| `test_negative_max_fee_raises` | `max_fee_sol = -0.001` → `ValueError` |
| `test_negative_failed_fee_raises` | `failed_tx_fee_sol = -1` → `ValueError` |
| `test_invalid_min_alert_score_low` | `min_alert_score = -1` → `ValueError` |
| `test_invalid_min_alert_score_high` | `min_alert_score = 101` → `ValueError` |
| `test_missing_secret_raises` | `auth.enabled=True`, `secret=""` → `ValueError` |
| `test_production_auth_disabled_raises` | `environment="production"`, `auth.enabled=False` → `ValueError` |
| `test_unknown_key_raises` | Config file contains `unknown_key = 1` → `ValueError` |
| `test_env_var_secret_resolved` | `secret="env:TEST_VAR"`, var set → secret loaded correctly |
| `test_env_var_missing_raises` | `secret="env:MISSING_VAR"`, var unset → `ValueError` |
| `test_toml_and_json_same_result` | Same config in both formats → equal `SentinelConfig` |

### `test_sentinel_auth.py`

| Test | What it asserts |
|---|---|
| `test_header_auth_success` | Correct secret in `Authorization` → pass |
| `test_header_auth_wrong_secret` | Wrong secret → 401 |
| `test_header_auth_missing_header` | No `Authorization` header → 401 |
| `test_hmac_auth_success` | Valid HMAC-SHA256 digest → pass |
| `test_hmac_auth_tampered_body` | Correct digest but body mutated → 401 |
| `test_auth_disabled_no_header` | `auth.enabled=False`, no header → pass |

### `test_sentinel_normalizer.py`

| Test | What it asserts |
|---|---|
| `test_array_format` | Array body → correct `WatchedEvent` count and field values |
| `test_envelope_format` | Envelope body → same output as array format |
| `test_event_id_deterministic` | Same inputs twice → identical `event_id` |
| `test_direction_all_four_cases` | All four `direction` values covered with minimal fixtures |
| `test_malformed_tx_skipped_rest_returned` | One bad tx in batch → rest returned; warning logged with `skipped_count` and `skipped_signatures` |
| `test_invalid_wallet_address_raises` | Bad address → `InvalidSolanaAddressError` |

### `test_sentinel_engine.py`

| Test | What it asserts |
|---|---|
| `test_large_sol_transfer_triggered` | `native_out_sol` above threshold → `LARGE_SOL_TRANSFER` in `triggered_rules` |
| `test_large_sol_transfer_not_triggered` | `native_out_sol` at or below threshold → absent |
| `test_known_bad_program_in_account_data` | Blacklisted address in `raw["accountData"]` → triggered |
| `test_known_bad_program_in_counterparty` | Blacklisted address in movement counterparty → triggered |
| `test_mass_drain_same_mint_not_triggered` | 4 movements of same mint → not triggered |
| `test_mass_drain_distinct_mints_triggered` | 4 different mints → triggered |
| `test_fee_spike_triggered` | `fee_sol > max_fee_sol` → triggered |
| `test_failed_high_fee_triggered` | Failed + `fee_paid_by_wallet` + high fee → triggered |
| `test_score_clamped_to_100` | Two heavy rules combined → final score ≤ 100 |
| `test_risk_level_bands` | Boundary scores (0, 24, 25, 49, 50, 79, 80, 100) → correct `risk_level` |
| `test_rule_result_has_reason` | Every triggerable rule produces non-empty `reason` string |
| `test_disabled_rule_not_triggered` | Rule toggled off in config → absent from `triggered_rules` |
| `test_new_counterparty_disabled_by_default` | `check_new_counterparty=False` → never fires |
| `test_new_counterparty_first_seen` | Opt-in enabled, first appearance → triggered |
| `test_new_counterparty_repeat` | Same address second time in same engine state → not triggered |

### `test_sentinel_dispatcher.py`

| Test | What it asserts |
|---|---|
| `test_logging_handler_sends` | Alert reaches `LoggingAlertHandler` without error |
| `test_file_handler_writes_jsonl` | Valid JSON line appended per alert |
| `test_file_handler_decimal_as_string` | `fee_sol` and other `Decimal` fields serialized as `str`, not `float` |
| `test_file_handler_failure_continues` | `IOError` on write → error logged, no exception propagated |
| `test_handler_failure_continues` | Crashing handler → error logged, next handler still called |
| `test_deduplication_same_rules` | Same `event_id` + same `triggered_rules` → second `dispatch` call skipped |
| `test_deduplication_different_rules` | Same `event_id`, different `triggered_rules` → not deduplicated |
| `test_deduplication_fresh_instance` | New `Dispatcher()` → previously seen pairs are dispatched again (clean state) |

### `test_sentinel_integration.py`

All tests use `app.test_client()` — no live server.

| Test | What it asserts |
|---|---|
| `test_full_pipeline_alert_triggered` | Valid POST → `FakeAlertHandler.received` has one entry with expected fields |
| `test_full_pipeline_below_threshold` | Score < `min_alert_score` → handler receives nothing |
| `test_unknown_wallet_no_alert` | Wallet not in `monitored_wallets` → 200, handler empty |
| `test_malformed_json_returns_400` | Non-JSON body → 400 |
| `test_no_op_event_no_alert` | Failed tx, no movements → score 0, no alert |
| `test_auth_rejects_bad_signature` | Wrong sig → 401, handler empty |
| `test_healthz` | `GET /healthz` → `{"status": "ok"}` |
| `test_two_monitored_wallets_same_tx` | Transaction with movements for two wallets both in `monitored_wallets` → two `WatchedEvent` objects emitted (one per wallet perspective), both scored and dispatched independently |
| `test_no_monitored_wallet_in_tx` | Transaction involving only wallets not in `monitored_wallets` → 200, zero alerts, `FakeAlertHandler.received` is empty |

---

## 13. Tech Debt & Extension Points

| Item | Target |
|---|---|
| Extract `_build_transaction_row` into public `parse_transaction(wallet_address, raw_tx) -> dict` | Pre-Sprint-2 task |
| Persistent deduplication state (file or SQLite) | Sprint 2 |
| `NEW_COUNTERPARTY` persistent seen-set | Sprint 2 |
| Price oracle integration and financial threshold alerts | Sprint 2 |
| `AlertPayload.tax_impact` field | Sprint 2 |
| `TelegramAlertHandler`, `DiscordAlertHandler`, `WebPushAlertHandler` | Sprint 2/3 |
| Legal RAG cross-reference in engine | Sprint 3 |
| `recommended_action_url` populated with Blink/Action URLs | Sprint 3 |
| `AlertPayload.legal_flags` field | Sprint 3 |
| LLM-generated `summary` replacing template-based generation | Sprint 3 |

---

## 14. Dependencies

```toml
[project.optional-dependencies]
sentinel = ["flask>=3.0.0"]
```

Install: `pip install -e ".[sentinel]"` or `pip install -e ".[dev,sentinel]"` for the full dev environment.

`flask>=3.0.0` is the only new runtime dependency. All other sentinel components use Python stdlib exclusively (`abc`, `dataclasses`, `decimal`, `hashlib`, `hmac`, `json`, `logging`). TOML config requires Python ≥ 3.11 (`tomllib` stdlib); JSON config works on Python ≥ 3.10.

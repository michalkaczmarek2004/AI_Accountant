# Sentinel Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time webhook monitoring layer (`ai_accountant.sentinel`) that receives Helius events, scores them for anomalies, and dispatches alerts — without touching any existing code.

**Architecture:** A Flask app factory (`create_app`) wires together a normalizer (reuses `SolanaDataFetcher._build_transaction_row`), a rule-based anomaly engine, and a pluggable `Dispatcher`. The sentinel is an optional sub-package; Flask is only imported inside it.

**Tech Stack:** Python ≥ 3.10, Flask ≥ 3.0, stdlib only elsewhere (`hashlib`, `hmac`, `json`, `logging`, `abc`, `dataclasses`, `decimal`). pytest + Flask `test_client()` for all tests.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `sentinel = ["flask>=3.0.0"]` optional dep |
| `src/ai_accountant/sentinel/__init__.py` | Create | Re-export `create_app`, `load_config`, `AlertHandler` |
| `src/ai_accountant/sentinel/models.py` | Create | `WatchedEvent`, `RuleResult`, `AnomalyScore`, `AlertPayload` frozen dataclasses |
| `src/ai_accountant/sentinel/config.py` | Create | `SentinelConfig` hierarchy, `load_config`, `_validate_config` |
| `src/ai_accountant/sentinel/auth.py` | Create | `authenticate_request` — header and HMAC modes |
| `src/ai_accountant/sentinel/normalizer.py` | Create | `normalize(payload, monitored_wallets)` → `list[WatchedEvent]` |
| `src/ai_accountant/sentinel/engine.py` | Create | `score_event` + 6 anomaly rules |
| `src/ai_accountant/sentinel/dispatcher.py` | Create | `AlertHandler` ABC, `Dispatcher`, `LoggingAlertHandler`, `FileAlertHandler` |
| `src/ai_accountant/sentinel/app.py` | Create | `create_app`, `/webhook`, `/healthz`, `_build_alert_payload` |
| `tests/conftest.py` | Create | Shared fixtures: `make_config`, `make_event`, `make_helius_payload`, `FakeAlertHandler` |
| `tests/test_sentinel_config.py` | Create | Config dataclass + loader + validation tests |
| `tests/test_sentinel_auth.py` | Create | Auth header and HMAC tests |
| `tests/test_sentinel_normalizer.py` | Create | Normalizer unit tests |
| `tests/test_sentinel_engine.py` | Create | Engine rule tests |
| `tests/test_sentinel_dispatcher.py` | Create | Dispatcher + handler tests |
| `tests/test_sentinel_integration.py` | Create | Full pipeline via `test_client()` |
| `sentinel_config.example.toml` | Create | Annotated reference config |

---

## Task 1: Project setup — package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/ai_accountant/sentinel/__init__.py` (empty stub)
- Create: `tests/conftest.py` (constants only — fixtures added per task)

- [ ] **Step 1: Add sentinel optional dependency to pyproject.toml**

Open `pyproject.toml` and add after the existing `[project.optional-dependencies]` section (create it if absent):

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
]
sentinel = ["flask>=3.0.0"]
```

- [ ] **Step 2: Create the sentinel package directory with an empty `__init__.py`**

```python
# src/ai_accountant/sentinel/__init__.py
# Populated in Task 15 after all modules exist.
```

- [ ] **Step 3: Install sentinel deps**

```
pip install -e ".[dev,sentinel]"
```

Expected: successful install, `flask` now importable.

- [ ] **Step 4: Create `tests/conftest.py` with shared constants**

```python
# tests/conftest.py
"""Shared test fixtures for the sentinel test suite."""
# Valid Solana Base58 addresses (32-byte public keys).
VALID_WALLET   = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
VALID_WALLET_2 = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
UNKNOWN_WALLET = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"
```

- [ ] **Step 5: Verify the package is importable**

```
python -c "from ai_accountant import SolanaDataFetcher; print('ok')"
```

Expected: `ok` — existing code unaffected.

- [ ] **Step 6: Commit**

```
git add pyproject.toml src/ai_accountant/sentinel/__init__.py tests/conftest.py
git commit -m "chore: scaffold sentinel sub-package and optional dep"
```

---

## Task 2: Data models (`models.py`)

**Files:**
- Create: `src/ai_accountant/sentinel/models.py`
- Create (add to): `tests/test_sentinel_models.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentinel_models.py
from decimal import Decimal
from ai_accountant.sentinel.models import WatchedEvent, RuleResult, AnomalyScore, AlertPayload

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"

def _make_event(**kw):
    defaults = dict(
        event_id="eid", signature="sig", wallet_address=WALLET,
        slot=None, timestamp_unix=None, timestamp=None,
        transaction_type="TRANSFER", source="SYSTEM_PROGRAM",
        fee_sol=Decimal("0"), fee_paid_by_wallet=False, fee_payer=None,
        native_in_sol=Decimal("0"), native_out_sol=Decimal("0"),
        native_net_sol=Decimal("0"), direction="neutral",
        movements_in=(), movements_out=(), status="succeeded", raw={},
    )
    defaults.update(kw)
    return WatchedEvent(**defaults)

def test_watched_event_is_frozen():
    event = _make_event()
    try:
        event.signature = "other"   # type: ignore[misc]
        assert False, "should have raised"
    except Exception:
        pass

def test_rule_result_not_triggered():
    r = RuleResult(rule_id="LARGE_SOL_TRANSFER", score_delta=0, reason=None)
    assert r.score_delta == 0
    assert r.reason is None

def test_rule_result_triggered():
    r = RuleResult(rule_id="FEE_SPIKE", score_delta=20, reason="Fee 0.05 SOL > max 0.01")
    assert r.score_delta == 20
    assert "0.05" in r.reason

def test_anomaly_score_fields():
    s = AnomalyScore(score=60, triggered_rules=["KNOWN_BAD_PROGRAM"],
                     reasons=["addr in blacklist"], risk_level="high")
    assert s.score == 60
    assert s.triggered_rules == ["KNOWN_BAD_PROGRAM"]

def test_alert_payload_recommended_action_none():
    event = _make_event()
    score = AnomalyScore(score=0, triggered_rules=[], reasons=[], risk_level="low")
    p = AlertPayload(event=event, score=score, severity="INFO",
                     summary="ok", recommended_action_url=None)
    assert p.recommended_action_url is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.models'`

- [ ] **Step 3: Implement `models.py`**

```python
# src/ai_accountant/sentinel/models.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class WatchedEvent:
    event_id: str
    signature: str
    wallet_address: str
    slot: int | None
    timestamp_unix: int | None
    timestamp: str | None
    transaction_type: str | None
    source: str | None
    fee_sol: Decimal
    fee_paid_by_wallet: bool
    fee_payer: str | None
    native_in_sol: Decimal
    native_out_sol: Decimal
    native_net_sol: Decimal
    direction: str                          # "in" | "out" | "mixed" | "neutral"
    movements_in: tuple[dict[str, Any], ...]
    movements_out: tuple[dict[str, Any], ...]
    status: str                             # "succeeded" | "failed"
    raw: dict[str, Any]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    score_delta: int
    reason: str | None


@dataclass(frozen=True)
class AnomalyScore:
    score: int
    triggered_rules: list[str]
    reasons: list[str]                      # non-None reasons from triggered rules
    risk_level: str                         # "low" | "medium" | "high" | "critical"


@dataclass(frozen=True)
class AlertPayload:
    event: WatchedEvent
    score: AnomalyScore
    severity: str                           # "INFO" | "WARNING" | "HIGH" | "CRITICAL"
    summary: str
    recommended_action_url: str | None      # None in Sprint 1; Sprint 3: Blink URL
    # extension point: tax_impact (Sprint 2), legal_flags (Sprint 3)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_sentinel_models.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Add `make_event` and `FakeAlertHandler` to conftest**

```python
# append to tests/conftest.py
from decimal import Decimal
from ai_accountant.sentinel.models import WatchedEvent, AnomalyScore, AlertPayload
from ai_accountant.sentinel.dispatcher import AlertHandler   # added in Task 11


def make_event(**overrides: object) -> WatchedEvent:
    defaults: dict = dict(
        event_id="test-event-id",
        signature="test-sig",
        wallet_address=VALID_WALLET,
        slot=None, timestamp_unix=None, timestamp=None,
        transaction_type="TRANSFER", source="SYSTEM_PROGRAM",
        fee_sol=Decimal("0"), fee_paid_by_wallet=False, fee_payer=None,
        native_in_sol=Decimal("0"), native_out_sol=Decimal("0"),
        native_net_sol=Decimal("0"), direction="neutral",
        movements_in=(), movements_out=(), status="succeeded", raw={},
    )
    defaults.update(overrides)
    return WatchedEvent(**defaults)


class FakeAlertHandler:
    """Captures AlertPayload objects for test assertions."""
    name = "FakeAlertHandler"

    def __init__(self) -> None:
        self.received: list[AlertPayload] = []

    def send(self, payload: AlertPayload) -> None:
        self.received.append(payload)
```

> Note: the `AlertHandler` import will fail until Task 11. Comment it out and uncomment it after Task 11.

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/sentinel/models.py tests/test_sentinel_models.py tests/conftest.py
git commit -m "feat(sentinel): data models — WatchedEvent, RuleResult, AnomalyScore, AlertPayload"
```

---

## Task 3: Config dataclasses + validation

**Files:**
- Create: `src/ai_accountant/sentinel/config.py`
- Create: `tests/test_sentinel_config.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentinel_config.py
import os
import json
import pytest
from decimal import Decimal
from pathlib import Path
from ai_accountant.sentinel.config import (
    SentinelConfig, AuthConfig, ThresholdConfig, RuleConfig, AlertConfig, load_config,
)

VALID_WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


def _minimal_raw() -> dict:
    """Minimal valid config dict (as parsed from JSON/TOML)."""
    return {
        "environment": "test",
        "monitored_wallets": [VALID_WALLET],
        "auth": {"enabled": False, "type": "header", "secret": ""},
        "thresholds": {},
        "rules": {},
        "alerts": {},
    }


def test_valid_config_from_dict():
    from ai_accountant.sentinel.config import _parse_config
    cfg = _parse_config(_minimal_raw())
    assert isinstance(cfg, SentinelConfig)
    assert VALID_WALLET in cfg.monitored_wallets
    assert cfg.environment == "test"


def test_empty_wallets_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["monitored_wallets"] = []
    with pytest.raises(ValueError, match="monitored_wallets"):
        _parse_config(raw)


def test_invalid_wallet_address_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["monitored_wallets"] = ["not-a-valid-address!!!"]
    with pytest.raises(ValueError):
        _parse_config(raw)


def test_negative_large_transfer_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["thresholds"] = {"large_transfer_sol": "-1"}
    with pytest.raises(ValueError, match="large_transfer_sol"):
        _parse_config(raw)


def test_negative_max_fee_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["thresholds"] = {"max_fee_sol": "-0.001"}
    with pytest.raises(ValueError, match="max_fee_sol"):
        _parse_config(raw)


def test_negative_failed_fee_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["thresholds"] = {"failed_tx_fee_sol": "-1"}
    with pytest.raises(ValueError, match="failed_tx_fee_sol"):
        _parse_config(raw)


def test_invalid_min_alert_score_low():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["alerts"] = {"min_alert_score": -1}
    with pytest.raises(ValueError, match="min_alert_score"):
        _parse_config(raw)


def test_invalid_min_alert_score_high():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["alerts"] = {"min_alert_score": 101}
    with pytest.raises(ValueError, match="min_alert_score"):
        _parse_config(raw)


def test_missing_secret_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["auth"] = {"enabled": True, "type": "header", "secret": ""}
    with pytest.raises(ValueError, match="secret"):
        _parse_config(raw)


def test_production_auth_disabled_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["environment"] = "production"
    raw["auth"] = {"enabled": False, "type": "header", "secret": ""}
    with pytest.raises(ValueError, match="production"):
        _parse_config(raw)


def test_unknown_key_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["unknown_key"] = 1
    with pytest.raises(ValueError, match="unknown_key"):
        _parse_config(raw)


def test_env_var_secret_resolved(monkeypatch):
    from ai_accountant.sentinel.config import _parse_config
    monkeypatch.setenv("TEST_SENTINEL_SECRET", "my-secret")
    raw = _minimal_raw()
    raw["auth"] = {"enabled": True, "type": "header", "secret": "env:TEST_SENTINEL_SECRET"}
    cfg = _parse_config(raw)
    assert cfg.auth.secret == "my-secret"


def test_env_var_missing_raises(monkeypatch):
    from ai_accountant.sentinel.config import _parse_config
    monkeypatch.delenv("MISSING_SENTINEL_VAR", raising=False)
    raw = _minimal_raw()
    raw["auth"] = {"enabled": True, "type": "header", "secret": "env:MISSING_SENTINEL_VAR"}
    with pytest.raises(ValueError, match="MISSING_SENTINEL_VAR"):
        _parse_config(raw)


def test_load_config_json(tmp_path):
    cfg_file = tmp_path / "sentinel.json"
    cfg_file.write_text(json.dumps(_minimal_raw()), encoding="utf-8")
    cfg = load_config(cfg_file)
    assert isinstance(cfg, SentinelConfig)


def test_unknown_key_in_auth_section_raises():
    from ai_accountant.sentinel.config import _parse_config
    raw = _minimal_raw()
    raw["auth"]["extra_field"] = "oops"
    with pytest.raises(ValueError, match="extra_field"):
        _parse_config(raw)
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.config'`

- [ ] **Step 3: Implement `config.py`**

```python
# src/ai_accountant/sentinel/config.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ai_accountant.solana_data_fetcher import SolanaDataFetcher, InvalidSolanaAddressError

# ---------------------------------------------------------------------------
# Known keys per section — used to reject unknown config entries
# ---------------------------------------------------------------------------
_KNOWN_TOP = {"environment", "monitored_wallets", "auth", "thresholds", "rules", "alerts"}
_KNOWN_AUTH = {"enabled", "type", "secret"}
_KNOWN_THRESHOLDS = {
    "large_transfer_sol", "max_fee_sol", "failed_tx_fee_sol", "mass_drain_token_count",
}
_KNOWN_RULES = {
    "check_large_sol_transfer", "check_known_bad_program", "check_mass_token_drain",
    "check_fee_spike", "check_failed_high_fee", "check_new_counterparty",
    "blacklisted_programs",
}
_KNOWN_ALERTS = {"min_alert_score", "enabled_handlers", "log_level", "file_alert_path"}


# ---------------------------------------------------------------------------
# Nested config dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthConfig:
    enabled: bool = True
    type: str = "header"    # "header" | "hmac"
    secret: str = ""        # resolved from "env:VAR" at load time


@dataclass(frozen=True)
class ThresholdConfig:
    large_transfer_sol: Decimal = Decimal("10.0")
    max_fee_sol: Decimal = Decimal("0.01")
    failed_tx_fee_sol: Decimal = Decimal("0.001")
    mass_drain_token_count: int = 3


@dataclass(frozen=True)
class RuleConfig:
    check_large_sol_transfer: bool = True
    check_known_bad_program: bool = True
    check_mass_token_drain: bool = True
    check_fee_spike: bool = True
    check_failed_high_fee: bool = True
    check_new_counterparty: bool = False
    blacklisted_programs: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AlertConfig:
    min_alert_score: int = 50
    enabled_handlers: tuple[str, ...] = ("logging",)   # "logging" | "file"
    log_level: str = "WARNING"
    file_alert_path: str = "sentinel_alerts.jsonl"     # only used when "file" in enabled_handlers


@dataclass(frozen=True)
class SentinelConfig:
    environment: str                         # "local" | "test" | "production"
    monitored_wallets: frozenset[str]
    auth: AuthConfig = field(default_factory=AuthConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    rules: RuleConfig = field(default_factory=RuleConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _check_unknown(raw: dict[str, Any], known: set[str], section: str) -> None:
    unknown = set(raw) - known
    if unknown:
        raise ValueError(
            f"Unknown config keys in [{section or 'root'}]: {sorted(unknown)}"
        )


def _resolve_secret(raw_secret: str) -> str:
    if raw_secret.startswith("env:"):
        var = raw_secret[4:]
        value = os.environ.get(var, "")
        if not value:
            raise ValueError(
                f"Auth secret env var '{var}' is unset or empty."
            )
        return value
    return raw_secret


def _to_decimal(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f"Config field '{name}' is not a valid decimal: {value!r}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate_config(cfg: SentinelConfig) -> None:
    if not cfg.monitored_wallets:
        raise ValueError("monitored_wallets must contain at least one address.")
    for addr in cfg.monitored_wallets:
        try:
            SolanaDataFetcher.validate_address(addr)
        except InvalidSolanaAddressError as exc:
            raise ValueError(f"Invalid wallet address in monitored_wallets: {exc}") from exc

    if cfg.environment not in {"local", "test", "production"}:
        raise ValueError(
            f"environment must be 'local', 'test', or 'production'; got {cfg.environment!r}"
        )
    if cfg.environment == "production" and not cfg.auth.enabled:
        raise ValueError("auth.enabled must be True in production environment.")

    if cfg.auth.enabled and not cfg.auth.secret:
        raise ValueError("auth.secret is required when auth.enabled is True.")
    if cfg.auth.type not in {"header", "hmac"}:
        raise ValueError(f"auth.type must be 'header' or 'hmac'; got {cfg.auth.type!r}")

    for fname in ("large_transfer_sol", "max_fee_sol", "failed_tx_fee_sol"):
        val = getattr(cfg.thresholds, fname)
        if val < 0:
            raise ValueError(f"thresholds.{fname} must be >= 0; got {val}")
    if cfg.thresholds.mass_drain_token_count < 1:
        raise ValueError("thresholds.mass_drain_token_count must be >= 1.")

    if not (0 <= cfg.alerts.min_alert_score <= 100):
        raise ValueError(
            f"alerts.min_alert_score must be in [0, 100]; got {cfg.alerts.min_alert_score}"
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _parse_config(raw: dict[str, Any]) -> SentinelConfig:
    _check_unknown(raw, _KNOWN_TOP, "root")

    raw_auth = raw.get("auth", {})
    _check_unknown(raw_auth, _KNOWN_AUTH, "auth")
    resolved_secret = _resolve_secret(str(raw_auth.get("secret", "")))
    auth = AuthConfig(
        enabled=bool(raw_auth.get("enabled", True)),
        type=str(raw_auth.get("type", "header")),
        secret=resolved_secret,
    )

    raw_thresh = raw.get("thresholds", {})
    _check_unknown(raw_thresh, _KNOWN_THRESHOLDS, "thresholds")
    thresholds = ThresholdConfig(
        large_transfer_sol=_to_decimal(raw_thresh.get("large_transfer_sol", "10.0"), "large_transfer_sol"),
        max_fee_sol=_to_decimal(raw_thresh.get("max_fee_sol", "0.01"), "max_fee_sol"),
        failed_tx_fee_sol=_to_decimal(raw_thresh.get("failed_tx_fee_sol", "0.001"), "failed_tx_fee_sol"),
        mass_drain_token_count=int(raw_thresh.get("mass_drain_token_count", 3)),
    )

    raw_rules = raw.get("rules", {})
    _check_unknown(raw_rules, _KNOWN_RULES, "rules")
    rules = RuleConfig(
        check_large_sol_transfer=bool(raw_rules.get("check_large_sol_transfer", True)),
        check_known_bad_program=bool(raw_rules.get("check_known_bad_program", True)),
        check_mass_token_drain=bool(raw_rules.get("check_mass_token_drain", True)),
        check_fee_spike=bool(raw_rules.get("check_fee_spike", True)),
        check_failed_high_fee=bool(raw_rules.get("check_failed_high_fee", True)),
        check_new_counterparty=bool(raw_rules.get("check_new_counterparty", False)),
        blacklisted_programs=frozenset(raw_rules.get("blacklisted_programs", [])),
    )

    raw_alerts = raw.get("alerts", {})
    _check_unknown(raw_alerts, _KNOWN_ALERTS, "alerts")
    raw_handlers = raw_alerts.get("enabled_handlers", ["logging"])
    alerts = AlertConfig(
        min_alert_score=int(raw_alerts.get("min_alert_score", 50)),
        enabled_handlers=tuple(raw_handlers),
        log_level=str(raw_alerts.get("log_level", "WARNING")),
        file_alert_path=str(raw_alerts.get("file_alert_path", "sentinel_alerts.jsonl")),
    )

    cfg = SentinelConfig(
        environment=str(raw.get("environment", "local")),
        monitored_wallets=frozenset(raw.get("monitored_wallets", [])),
        auth=auth,
        thresholds=thresholds,
        rules=rules,
        alerts=alerts,
    )
    _validate_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------
def load_config(path: str | Path) -> SentinelConfig:
    path = Path(path)
    if path.suffix == ".toml":
        try:
            import tomllib
        except ImportError as exc:
            raise ImportError(
                "TOML config requires Python >= 3.11. Use a .json config file on Python 3.10."
            ) from exc
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    elif path.suffix == ".json":
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        raise ValueError(f"Config must be .toml or .json; got: {path.suffix!r}")
    return _parse_config(raw)
```

- [ ] **Step 4: Run config tests**

```
pytest tests/test_sentinel_config.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Add `make_config` to `tests/conftest.py`**

```python
# append to tests/conftest.py
from ai_accountant.sentinel.config import (
    SentinelConfig, AuthConfig, ThresholdConfig, RuleConfig, AlertConfig,
)


def make_config(
    environment: str = "test",
    monitored_wallets: frozenset | None = None,
    auth: AuthConfig | None = None,
    thresholds: ThresholdConfig | None = None,
    rules: RuleConfig | None = None,
    alerts: AlertConfig | None = None,
) -> SentinelConfig:
    """SentinelConfig with safe test defaults (auth disabled, min_alert_score=0)."""
    return SentinelConfig(
        environment=environment,
        monitored_wallets=monitored_wallets or frozenset({VALID_WALLET}),
        auth=auth or AuthConfig(enabled=False),
        thresholds=thresholds or ThresholdConfig(),
        rules=rules or RuleConfig(),
        alerts=alerts or AlertConfig(min_alert_score=0),
    )
```

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/sentinel/config.py tests/test_sentinel_config.py tests/conftest.py
git commit -m "feat(sentinel): config dataclasses, loader, and validation"
```

---

## Task 4: Authentication (`auth.py`)

**Files:**
- Create: `src/ai_accountant/sentinel/auth.py`
- Create: `tests/test_sentinel_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentinel_auth.py
import hashlib
import hmac
import json
import pytest
from ai_accountant.sentinel.auth import authenticate_request
from ai_accountant.sentinel.config import AuthConfig
from conftest import make_config

SECRET = "test-webhook-secret"


def _make_auth_config(enabled=True, type="header", secret=SECRET):
    return AuthConfig(enabled=enabled, type=type, secret=secret)


class FakeRequest:
    """Minimal stand-in for Flask request."""
    def __init__(self, headers: dict, data: bytes = b"{}"):
        self.headers = headers
        self.data = data


def test_header_auth_success():
    req = FakeRequest({"Authorization": SECRET})
    cfg = make_config(auth=_make_auth_config())
    assert authenticate_request(req, cfg) is True


def test_header_auth_wrong_secret():
    req = FakeRequest({"Authorization": "wrong-secret"})
    cfg = make_config(auth=_make_auth_config())
    assert authenticate_request(req, cfg) is False


def test_header_auth_missing_header():
    req = FakeRequest({})
    cfg = make_config(auth=_make_auth_config())
    assert authenticate_request(req, cfg) is False


def test_hmac_auth_success():
    body = b'[{"signature":"abc"}]'
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = FakeRequest({"Authorization": digest}, data=body)
    cfg = make_config(auth=_make_auth_config(type="hmac"))
    assert authenticate_request(req, cfg) is True


def test_hmac_auth_tampered_body():
    body = b'[{"signature":"abc"}]'
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = FakeRequest({"Authorization": digest}, data=b"tampered")
    cfg = make_config(auth=_make_auth_config(type="hmac"))
    assert authenticate_request(req, cfg) is False


def test_auth_disabled_no_header():
    req = FakeRequest({})
    cfg = make_config(auth=AuthConfig(enabled=False))
    assert authenticate_request(req, cfg) is True
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.auth'`

- [ ] **Step 3: Implement `auth.py`**

```python
# src/ai_accountant/sentinel/auth.py
from __future__ import annotations

import hashlib
import hmac
from typing import Any

from ai_accountant.sentinel.config import SentinelConfig


def authenticate_request(request: Any, config: SentinelConfig) -> bool:
    """Return True if the request passes authentication, False to reject with 401."""
    if not config.auth.enabled:
        return True

    header_value = request.headers.get("Authorization", "")
    if not header_value:
        return False

    if config.auth.type == "header":
        return hmac.compare_digest(header_value, config.auth.secret)

    if config.auth.type == "hmac":
        expected = hmac.new(
            config.auth.secret.encode(),
            request.data,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(header_value, expected)

    return False
```

- [ ] **Step 4: Run auth tests**

```
pytest tests/test_sentinel_auth.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/auth.py tests/test_sentinel_auth.py
git commit -m "feat(sentinel): webhook authentication — header and HMAC modes"
```

---

## Task 5: Normalizer — foundations

**Files:**
- Create: `src/ai_accountant/sentinel/normalizer.py`
- Create: `tests/test_sentinel_normalizer.py` (skeleton)

The normalizer has two non-trivial private helpers: `_compute_event_id` and `_compute_direction`. Build and test them before wiring up `normalize()`.

- [ ] **Step 1: Write failing tests for helpers**

```python
# tests/test_sentinel_normalizer.py
import hashlib
from decimal import Decimal
import pytest
from ai_accountant.sentinel.normalizer import (
    _compute_direction, _compute_event_id, _extract_transactions,
)

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


def test_direction_in():
    assert _compute_direction(Decimal("1"), Decimal("0")) == "in"

def test_direction_out():
    assert _compute_direction(Decimal("0"), Decimal("1")) == "out"

def test_direction_mixed():
    assert _compute_direction(Decimal("1"), Decimal("1")) == "mixed"

def test_direction_neutral():
    assert _compute_direction(Decimal("0"), Decimal("0")) == "neutral"

def test_event_id_deterministic():
    eid1 = _compute_event_id("sig", WALLET, "SWAP", Decimal("1.5"), "JUPITER")
    eid2 = _compute_event_id("sig", WALLET, "SWAP", Decimal("1.5"), "JUPITER")
    assert eid1 == eid2

def test_event_id_changes_on_different_wallet():
    eid1 = _compute_event_id("sig", WALLET, "SWAP", Decimal("1.5"), "JUPITER")
    eid2 = _compute_event_id("sig", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                              "SWAP", Decimal("1.5"), "JUPITER")
    assert eid1 != eid2

def test_event_id_is_hex_sha256():
    eid = _compute_event_id("sig", WALLET, None, Decimal("0"), None)
    assert len(eid) == 64
    int(eid, 16)  # must be valid hex

def test_extract_transactions_array_format():
    payload = [{"signature": "a"}, {"signature": "b"}]
    assert _extract_transactions(payload) == payload

def test_extract_transactions_envelope_format():
    txs = [{"signature": "a"}]
    payload = {"type": "TRANSACTION", "transactions": txs}
    assert _extract_transactions(payload) == txs

def test_extract_transactions_empty_array():
    assert _extract_transactions([]) == []
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_normalizer.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.normalizer'`

- [ ] **Step 3: Implement `normalizer.py` foundations**

```python
# src/ai_accountant/sentinel/normalizer.py
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any

from ai_accountant.solana_data_fetcher import SolanaDataFetcher
from ai_accountant.sentinel.models import WatchedEvent

logger = logging.getLogger(__name__)


class _NoOpSession:
    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Sentinel normalizer makes no HTTP requests.")

    def close(self) -> None:
        return None


_fetcher: SolanaDataFetcher | None = None


def _get_fetcher() -> SolanaDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = SolanaDataFetcher(api_key="sentinel-internal", session=_NoOpSession())
    return _fetcher


def _compute_direction(native_in: Decimal, native_out: Decimal) -> str:
    if native_in > 0 and native_out == 0:
        return "in"
    if native_out > 0 and native_in == 0:
        return "out"
    if native_in > 0 and native_out > 0:
        return "mixed"
    return "neutral"


def _compute_event_id(
    signature: str,
    wallet_address: str,
    transaction_type: str | None,
    native_net_sol: Decimal,
    source: str | None,
) -> str:
    parts = "|".join([
        signature,
        wallet_address,
        transaction_type or "",
        str(native_net_sol),
        source or "",
    ])
    return hashlib.sha256(parts.encode()).hexdigest()


def _extract_transactions(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("transactions", [])
    return []
```

- [ ] **Step 4: Run normalizer foundation tests**

```
pytest tests/test_sentinel_normalizer.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/normalizer.py tests/test_sentinel_normalizer.py
git commit -m "feat(sentinel): normalizer foundations — event_id, direction, extract_transactions"
```

---

## Task 6: Normalizer — `normalize()` with multi-wallet support

**Files:**
- Modify: `src/ai_accountant/sentinel/normalizer.py`
- Modify: `tests/test_sentinel_normalizer.py`

- [ ] **Step 1: Add tests for `normalize()`**

Append to `tests/test_sentinel_normalizer.py`:

```python
from ai_accountant.sentinel.normalizer import normalize

WALLET   = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
WALLET_2 = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
OTHER    = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"


def _tx(sig="sig1", from_=WALLET, to=OTHER, amount=1_000_000_000):
    return {
        "signature": sig, "slot": 1, "timestamp": 1700000000,
        "type": "TRANSFER", "source": "SYSTEM_PROGRAM",
        "fee": 5000, "feePayer": from_,
        "nativeTransfers": [
            {"fromUserAccount": from_, "toUserAccount": to, "amount": amount}
        ],
        "tokenTransfers": [],
    }


def test_normalize_basic_event():
    events = normalize([_tx()], frozenset({WALLET}))
    assert len(events) == 1
    e = events[0]
    assert e.wallet_address == WALLET
    assert e.native_out_sol > 0
    assert e.direction == "out"


def test_normalize_array_and_envelope_same_result():
    tx = _tx()
    from_array = normalize([tx], frozenset({WALLET}))
    from_env   = normalize({"type": "TRANSACTION", "transactions": [tx]}, frozenset({WALLET}))
    assert len(from_array) == len(from_env) == 1
    assert from_array[0].event_id == from_env[0].event_id


def test_normalize_two_monitored_wallets_same_tx():
    tx = _tx(from_=WALLET, to=WALLET_2)
    events = normalize([tx], frozenset({WALLET, WALLET_2}))
    assert len(events) == 2
    wallets = {e.wallet_address for e in events}
    assert wallets == {WALLET, WALLET_2}


def test_normalize_no_monitored_wallet_in_tx_returns_empty():
    tx = _tx(from_=OTHER, to="DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW")
    events = normalize([tx], frozenset({WALLET}))
    assert events == []


def test_normalize_malformed_tx_skipped_rest_returned(caplog):
    import logging
    good = _tx(sig="good")
    bad  = {"signature": "bad", "fee": "NOT_A_NUMBER", "nativeTransfers": "oops"}
    with caplog.at_level(logging.WARNING, logger="ai_accountant.sentinel.normalizer"):
        events = normalize([bad, good], frozenset({WALLET}))
    sigs = [e.signature for e in events]
    assert "good" in sigs
    assert any("bad" in r.message or "skipped" in r.message.lower() for r in caplog.records)


def test_normalize_event_id_deterministic():
    tx = _tx()
    e1 = normalize([tx], frozenset({WALLET}))[0]
    e2 = normalize([tx], frozenset({WALLET}))[0]
    assert e1.event_id == e2.event_id


def test_normalize_wallet_not_in_tx_produces_no_event():
    # WALLET_2 is monitored but not in this transaction at all
    tx = _tx(from_=WALLET, to=OTHER)
    events = normalize([tx], frozenset({WALLET, WALLET_2}))
    wallets = {e.wallet_address for e in events}
    assert WALLET_2 not in wallets
```

- [ ] **Step 2: Run to verify new tests fail**

```
pytest tests/test_sentinel_normalizer.py::test_normalize_basic_event -v
```

Expected: `ImportError` — `normalize` not yet defined.

- [ ] **Step 3: Add `normalize` and `_build_watched_event` to `normalizer.py`**

Append to the bottom of `src/ai_accountant/sentinel/normalizer.py`:

```python
def _build_watched_event(
    wallet_address: str,
    tx: dict[str, Any],
    row: dict[str, Any],
) -> WatchedEvent:
    native_in  = row["native_in_sol"]
    native_out = row["native_out_sol"]
    return WatchedEvent(
        event_id=_compute_event_id(
            row["signature"] or "",
            wallet_address,
            row["transaction_type"],
            row["native_net_sol"],
            row["source"],
        ),
        signature=row["signature"] or "",
        wallet_address=wallet_address,
        slot=row["slot"],
        timestamp_unix=row["timestamp_unix"],
        timestamp=row["timestamp"],
        transaction_type=row["transaction_type"],
        source=row["source"],
        fee_sol=row["fee_sol"],
        fee_paid_by_wallet=row["fee_paid_by_wallet"],
        fee_payer=row["fee_payer"],
        native_in_sol=native_in,
        native_out_sol=native_out,
        native_net_sol=row["native_net_sol"],
        direction=_compute_direction(native_in, native_out),
        movements_in=tuple(row["movements_in"]),
        movements_out=tuple(row["movements_out"]),
        status=row["status"],
        raw=tx,
    )


def normalize(
    payload: dict | list,
    monitored_wallets: frozenset[str],
) -> list[WatchedEvent]:
    """
    Return one WatchedEvent per (transaction, wallet_address) pair where the
    wallet appears in the transaction's movements or paid the fee.
    Wallets not in monitored_wallets are silently ignored (not an error).
    """
    transactions = _extract_transactions(payload)
    fetcher = _get_fetcher()

    events: list[WatchedEvent] = []
    skipped_signatures: list[str] = []

    for tx in transactions:
        for wallet_address in monitored_wallets:
            try:
                row = fetcher._build_transaction_row(wallet_address, tx)
            except Exception as exc:
                sig = str(tx.get("signature", "unknown"))
                if sig not in skipped_signatures:
                    skipped_signatures.append(sig)
                logger.debug("Skipping malformed tx %s for wallet %s: %s", sig, wallet_address, exc)
                continue

            has_involvement = (
                row["movements_in"]
                or row["movements_out"]
                or row["fee_paid_by_wallet"]
            )
            if not has_involvement:
                continue

            events.append(_build_watched_event(wallet_address, tx, row))

    if skipped_signatures:
        logger.warning(
            "Skipped %d malformed transaction(s): %s",
            len(skipped_signatures),
            skipped_signatures,
        )

    return events
```

- [ ] **Step 4: Run all normalizer tests**

```
pytest tests/test_sentinel_normalizer.py -v
```

Expected: all 17 tests PASS.

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/normalizer.py tests/test_sentinel_normalizer.py
git commit -m "feat(sentinel): normalize() with multi-wallet support and error isolation"
```

---

## Task 7: Anomaly engine — framework + basic rules

**Files:**
- Create: `src/ai_accountant/sentinel/engine.py`
- Create: `tests/test_sentinel_engine.py`

This task covers `score_event`, `_risk_level`, and three rules: `LARGE_SOL_TRANSFER`, `FEE_SPIKE`, `FAILED_HIGH_FEE`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentinel_engine.py
from decimal import Decimal
import pytest
from ai_accountant.sentinel.engine import score_event, _risk_level, _reset_seen_counterparties
from ai_accountant.sentinel.config import ThresholdConfig, RuleConfig
from conftest import make_config, make_event


def test_risk_level_bands():
    assert _risk_level(0)   == "low"
    assert _risk_level(24)  == "low"
    assert _risk_level(25)  == "medium"
    assert _risk_level(49)  == "medium"
    assert _risk_level(50)  == "high"
    assert _risk_level(79)  == "high"
    assert _risk_level(80)  == "critical"
    assert _risk_level(100) == "critical"


def test_clean_event_scores_zero():
    cfg = make_config()
    event = make_event()
    score = score_event(cfg, event)
    assert score.score == 0
    assert score.triggered_rules == []
    assert score.risk_level == "low"


def test_large_sol_transfer_triggered():
    cfg = make_config(thresholds=ThresholdConfig(large_transfer_sol=Decimal("2.0")))
    event = make_event(native_out_sol=Decimal("5.0"))
    score = score_event(cfg, event)
    assert "LARGE_SOL_TRANSFER" in score.triggered_rules
    assert score.score >= 40
    assert any("5" in r for r in score.reasons)


def test_large_sol_transfer_not_triggered():
    cfg = make_config(thresholds=ThresholdConfig(large_transfer_sol=Decimal("10.0")))
    event = make_event(native_out_sol=Decimal("2.0"))
    score = score_event(cfg, event)
    assert "LARGE_SOL_TRANSFER" not in score.triggered_rules


def test_large_sol_transfer_disabled():
    cfg = make_config(rules=RuleConfig(check_large_sol_transfer=False))
    event = make_event(native_out_sol=Decimal("100.0"))
    score = score_event(cfg, event)
    assert "LARGE_SOL_TRANSFER" not in score.triggered_rules


def test_fee_spike_triggered():
    cfg = make_config(thresholds=ThresholdConfig(max_fee_sol=Decimal("0.01")))
    event = make_event(fee_sol=Decimal("0.05"), fee_paid_by_wallet=True)
    score = score_event(cfg, event)
    assert "FEE_SPIKE" in score.triggered_rules


def test_fee_spike_not_triggered():
    cfg = make_config(thresholds=ThresholdConfig(max_fee_sol=Decimal("0.01")))
    event = make_event(fee_sol=Decimal("0.001"))
    score = score_event(cfg, event)
    assert "FEE_SPIKE" not in score.triggered_rules


def test_failed_high_fee_triggered():
    cfg = make_config(thresholds=ThresholdConfig(failed_tx_fee_sol=Decimal("0.001")))
    event = make_event(status="failed", fee_paid_by_wallet=True, fee_sol=Decimal("0.005"))
    score = score_event(cfg, event)
    assert "FAILED_HIGH_FEE" in score.triggered_rules


def test_failed_high_fee_not_triggered_if_fee_not_paid():
    cfg = make_config()
    event = make_event(status="failed", fee_paid_by_wallet=False, fee_sol=Decimal("0.1"))
    score = score_event(cfg, event)
    assert "FAILED_HIGH_FEE" not in score.triggered_rules


def test_score_clamped_to_100():
    cfg = make_config()
    # LARGE_SOL_TRANSFER (40) + FEE_SPIKE (20) + FAILED_HIGH_FEE (15) = 75, not clamped here
    # To force clamping, trigger LARGE + KNOWN_BAD_PROGRAM
    from ai_accountant.sentinel.config import RuleConfig
    cfg2 = make_config(
        rules=RuleConfig(
            blacklisted_programs=frozenset({"bad-program"}),
        ),
        thresholds=ThresholdConfig(
            large_transfer_sol=Decimal("1.0"),
            max_fee_sol=Decimal("0.001"),
            mass_drain_token_count=1,
        ),
    )
    event = make_event(
        native_out_sol=Decimal("5.0"),
        fee_sol=Decimal("0.05"),
        movements_out=(
            {"asset_type": "token", "mint": "mintA", "counterparty": "bad-program",
             "symbol": "TOK", "amount": Decimal("1")},
            {"asset_type": "token", "mint": "mintB", "counterparty": "other",
             "symbol": "TOK2", "amount": Decimal("1")},
        ),
        raw={"accountData": [{"account": "bad-program"}]},
    )
    score = score_event(cfg2, event)
    assert score.score <= 100


def test_rule_result_has_reason():
    cfg = make_config(thresholds=ThresholdConfig(large_transfer_sol=Decimal("1.0")))
    event = make_event(native_out_sol=Decimal("5.0"))
    score = score_event(cfg, event)
    assert score.reasons
    assert all(isinstance(r, str) and len(r) > 0 for r in score.reasons)
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.engine'`

- [ ] **Step 3: Implement `engine.py` with basic rules**

```python
# src/ai_accountant/sentinel/engine.py
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from ai_accountant.sentinel.config import SentinelConfig
from ai_accountant.sentinel.models import AnomalyScore, RuleResult, WatchedEvent

# In-memory seen counterparties for NEW_COUNTERPARTY rule.
_seen_counterparties: set[str] = set()


def _reset_seen_counterparties() -> None:
    """For tests only — resets NEW_COUNTERPARTY in-memory state."""
    global _seen_counterparties
    _seen_counterparties = set()


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Rules — each returns RuleResult (score_delta=0 when not triggered)
# ---------------------------------------------------------------------------

def _rule_large_sol_transfer(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    threshold = config.thresholds.large_transfer_sol
    if event.native_out_sol > threshold:
        return RuleResult(
            rule_id="LARGE_SOL_TRANSFER",
            score_delta=40,
            reason=(
                f"Outgoing {event.native_out_sol} SOL exceeded threshold {threshold} SOL"
            ),
        )
    return RuleResult(rule_id="LARGE_SOL_TRANSFER", score_delta=0, reason=None)


def _rule_fee_spike(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    threshold = config.thresholds.max_fee_sol
    if event.fee_sol > threshold:
        return RuleResult(
            rule_id="FEE_SPIKE",
            score_delta=20,
            reason=f"Fee {event.fee_sol} SOL exceeded max {threshold} SOL",
        )
    return RuleResult(rule_id="FEE_SPIKE", score_delta=0, reason=None)


def _rule_failed_high_fee(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    threshold = config.thresholds.failed_tx_fee_sol
    if event.status == "failed" and event.fee_paid_by_wallet and event.fee_sol > threshold:
        return RuleResult(
            rule_id="FAILED_HIGH_FEE",
            score_delta=15,
            reason=(
                f"Failed tx consumed fee {event.fee_sol} SOL > threshold {threshold} SOL"
            ),
        )
    return RuleResult(rule_id="FAILED_HIGH_FEE", score_delta=0, reason=None)


# Populated below after all rules are defined.
_ALL_RULES: list[tuple[str, Callable]] = []


def _enabled_rules(config: SentinelConfig) -> list[Callable]:
    toggle = {
        "LARGE_SOL_TRANSFER": config.rules.check_large_sol_transfer,
        "FEE_SPIKE":          config.rules.check_fee_spike,
        "FAILED_HIGH_FEE":    config.rules.check_failed_high_fee,
        "KNOWN_BAD_PROGRAM":  config.rules.check_known_bad_program,
        "MASS_TOKEN_DRAIN":   config.rules.check_mass_token_drain,
        "NEW_COUNTERPARTY":   config.rules.check_new_counterparty,
    }
    return [fn for rule_id, fn in _ALL_RULES if toggle.get(rule_id, True)]


def score_event(config: SentinelConfig, event: WatchedEvent) -> AnomalyScore:
    results = [fn(config, event) for fn in _enabled_rules(config)]
    triggered = [r for r in results if r.score_delta > 0]
    total = min(sum(r.score_delta for r in triggered), 100)
    return AnomalyScore(
        score=total,
        triggered_rules=[r.rule_id for r in triggered],
        reasons=[r.reason for r in triggered if r.reason is not None],
        risk_level=_risk_level(total),
    )
```

Add at the bottom of `engine.py` (after all rule functions defined):

```python
_ALL_RULES = [
    ("LARGE_SOL_TRANSFER", _rule_large_sol_transfer),
    ("FEE_SPIKE",          _rule_fee_spike),
    ("FAILED_HIGH_FEE",    _rule_failed_high_fee),
    # KNOWN_BAD_PROGRAM, MASS_TOKEN_DRAIN, NEW_COUNTERPARTY added in Task 8
]
```

- [ ] **Step 4: Run engine tests**

```
pytest tests/test_sentinel_engine.py -v
```

Expected: all 11 basic-rule tests PASS. (Complex-rule tests don't exist yet.)

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/engine.py tests/test_sentinel_engine.py
git commit -m "feat(sentinel): anomaly engine framework + LARGE_SOL_TRANSFER, FEE_SPIKE, FAILED_HIGH_FEE rules"
```

---

## Task 8: Anomaly engine — complex rules

**Files:**
- Modify: `src/ai_accountant/sentinel/engine.py`
- Modify: `tests/test_sentinel_engine.py`

- [ ] **Step 1: Add failing tests for KNOWN_BAD_PROGRAM, MASS_TOKEN_DRAIN, NEW_COUNTERPARTY**

Append to `tests/test_sentinel_engine.py`:

```python
from ai_accountant.sentinel.engine import _reset_seen_counterparties


def test_known_bad_program_in_account_data():
    cfg = make_config(rules=RuleConfig(blacklisted_programs=frozenset({"bad-addr"})))
    event = make_event(raw={"accountData": [{"account": "bad-addr"}, {"account": "ok"}]})
    score = score_event(cfg, event)
    assert "KNOWN_BAD_PROGRAM" in score.triggered_rules
    assert score.score >= 60


def test_known_bad_program_in_counterparty():
    cfg = make_config(rules=RuleConfig(blacklisted_programs=frozenset({"evil"})))
    event = make_event(
        movements_out=({"asset_type": "native", "mint": None, "counterparty": "evil",
                         "symbol": "SOL", "amount": Decimal("1")},),
    )
    score = score_event(cfg, event)
    assert "KNOWN_BAD_PROGRAM" in score.triggered_rules


def test_known_bad_program_not_triggered_empty_blacklist():
    cfg = make_config(rules=RuleConfig(blacklisted_programs=frozenset()))
    event = make_event(raw={"accountData": [{"account": "any-addr"}]})
    score = score_event(cfg, event)
    assert "KNOWN_BAD_PROGRAM" not in score.triggered_rules


def test_mass_drain_same_mint_not_triggered():
    cfg = make_config(thresholds=ThresholdConfig(mass_drain_token_count=3))
    # 4 movements but all same mint — distinct mints = 1, below threshold
    movements = tuple(
        {"asset_type": "token", "mint": "mintA", "counterparty": "x",
         "symbol": "TOK", "amount": Decimal("1")}
        for _ in range(4)
    )
    event = make_event(movements_out=movements)
    score = score_event(cfg, event)
    assert "MASS_TOKEN_DRAIN" not in score.triggered_rules


def test_mass_drain_distinct_mints_triggered():
    cfg = make_config(thresholds=ThresholdConfig(mass_drain_token_count=3))
    movements = tuple(
        {"asset_type": "token", "mint": f"mint{i}", "counterparty": "x",
         "symbol": f"TOK{i}", "amount": Decimal("1")}
        for i in range(4)
    )
    event = make_event(movements_out=movements)
    score = score_event(cfg, event)
    assert "MASS_TOKEN_DRAIN" in score.triggered_rules
    assert score.score >= 50


def test_new_counterparty_disabled_by_default():
    cfg = make_config(rules=RuleConfig(check_new_counterparty=False))
    event = make_event(movements_in=(
        {"asset_type": "native", "counterparty": "brand-new", "mint": None,
         "symbol": "SOL", "amount": Decimal("1")},
    ))
    score = score_event(cfg, event)
    assert "NEW_COUNTERPARTY" not in score.triggered_rules


def test_new_counterparty_first_seen_triggered():
    _reset_seen_counterparties()
    cfg = make_config(rules=RuleConfig(check_new_counterparty=True))
    event = make_event(movements_in=(
        {"asset_type": "native", "counterparty": "never-seen", "mint": None,
         "symbol": "SOL", "amount": Decimal("1")},
    ))
    score = score_event(cfg, event)
    assert "NEW_COUNTERPARTY" in score.triggered_rules


def test_new_counterparty_not_triggered_on_repeat():
    _reset_seen_counterparties()
    cfg = make_config(rules=RuleConfig(check_new_counterparty=True))
    event = make_event(movements_in=(
        {"asset_type": "native", "counterparty": "repeat-addr", "mint": None,
         "symbol": "SOL", "amount": Decimal("1")},
    ))
    score_event(cfg, event)          # first time — marks as seen
    score2 = score_event(cfg, event)  # second time — should not trigger
    assert "NEW_COUNTERPARTY" not in score2.triggered_rules
```

- [ ] **Step 2: Run to verify new tests fail**

```
pytest tests/test_sentinel_engine.py::test_known_bad_program_in_account_data -v
```

Expected: FAIL — rule not implemented.

- [ ] **Step 3: Add complex rules to `engine.py`**

Insert before the `_ALL_RULES` list at the bottom of `engine.py`:

```python
def _rule_known_bad_program(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    blacklist = config.rules.blacklisted_programs
    if not blacklist:
        return RuleResult(rule_id="KNOWN_BAD_PROGRAM", score_delta=0, reason=None)

    # Check accountData in raw payload
    for entry in event.raw.get("accountData", []):
        addr = entry.get("account", "")
        if addr in blacklist:
            return RuleResult(
                rule_id="KNOWN_BAD_PROGRAM",
                score_delta=60,
                reason=f"Blacklisted address in accountData: {addr}",
            )

    # Check movement counterparties
    all_movements = list(event.movements_in) + list(event.movements_out)
    for mov in all_movements:
        cp = mov.get("counterparty", "")
        if cp and cp in blacklist:
            return RuleResult(
                rule_id="KNOWN_BAD_PROGRAM",
                score_delta=60,
                reason=f"Blacklisted counterparty in movements: {cp}",
            )

    return RuleResult(rule_id="KNOWN_BAD_PROGRAM", score_delta=0, reason=None)


def _rule_mass_token_drain(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    threshold = config.thresholds.mass_drain_token_count
    distinct_mints = {
        mov.get("mint")
        for mov in event.movements_out
        if mov.get("asset_type") == "token" and mov.get("mint")
    }
    if len(distinct_mints) > threshold:
        return RuleResult(
            rule_id="MASS_TOKEN_DRAIN",
            score_delta=50,
            reason=(
                f"{len(distinct_mints)} distinct token mints drained "
                f"(threshold {threshold})"
            ),
        )
    return RuleResult(rule_id="MASS_TOKEN_DRAIN", score_delta=0, reason=None)


def _rule_new_counterparty(config: SentinelConfig, event: WatchedEvent) -> RuleResult:
    all_movements = list(event.movements_in) + list(event.movements_out)
    new_ones: list[str] = []
    for mov in all_movements:
        cp = mov.get("counterparty")
        if cp and cp not in _seen_counterparties:
            new_ones.append(cp)

    if new_ones:
        _seen_counterparties.update(new_ones)
        return RuleResult(
            rule_id="NEW_COUNTERPARTY",
            score_delta=10,
            reason=f"New counterparty/counterparties first seen: {new_ones[:3]}",
        )
    return RuleResult(rule_id="NEW_COUNTERPARTY", score_delta=0, reason=None)
```

Replace `_ALL_RULES` with the full list:

```python
_ALL_RULES = [
    ("LARGE_SOL_TRANSFER", _rule_large_sol_transfer),
    ("FEE_SPIKE",          _rule_fee_spike),
    ("FAILED_HIGH_FEE",    _rule_failed_high_fee),
    ("KNOWN_BAD_PROGRAM",  _rule_known_bad_program),
    ("MASS_TOKEN_DRAIN",   _rule_mass_token_drain),
    ("NEW_COUNTERPARTY",   _rule_new_counterparty),
]
```

- [ ] **Step 4: Run all engine tests**

```
pytest tests/test_sentinel_engine.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/engine.py tests/test_sentinel_engine.py
git commit -m "feat(sentinel): KNOWN_BAD_PROGRAM, MASS_TOKEN_DRAIN, NEW_COUNTERPARTY rules"
```

---

## Task 9: Alert dispatcher

**Files:**
- Create: `src/ai_accountant/sentinel/dispatcher.py`
- Create: `tests/test_sentinel_dispatcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentinel_dispatcher.py
import json
import logging
from decimal import Decimal
from pathlib import Path
import pytest

from ai_accountant.sentinel.dispatcher import (
    AlertHandler, Dispatcher, LoggingAlertHandler, FileAlertHandler,
)
from ai_accountant.sentinel.models import AnomalyScore, AlertPayload
from conftest import make_event, FakeAlertHandler


def _make_score(score=60, rules=None):
    rules = rules or ["LARGE_SOL_TRANSFER"]
    return AnomalyScore(
        score=score, triggered_rules=rules,
        reasons=[f"reason for {r}" for r in rules],
        risk_level="high" if score >= 50 else "low",
    )


def _make_payload(event=None, score=None, severity="HIGH"):
    return AlertPayload(
        event=event or make_event(fee_sol=Decimal("0.05")),
        score=score or _make_score(),
        severity=severity,
        summary="[HIGH] test alert",
        recommended_action_url=None,
    )


def test_fake_handler_is_alert_handler():
    assert isinstance(FakeAlertHandler(), AlertHandler)


def test_dispatcher_calls_handler():
    handler = FakeAlertHandler()
    d = Dispatcher([handler])
    payload = _make_payload()
    d.dispatch(payload)
    assert len(handler.received) == 1
    assert handler.received[0] is payload


def test_dispatcher_deduplication_same_rules():
    handler = FakeAlertHandler()
    d = Dispatcher([handler])
    payload = _make_payload()
    d.dispatch(payload)
    d.dispatch(payload)     # same event_id + same rules → deduplicated
    assert len(handler.received) == 1


def test_dispatcher_deduplication_different_rules():
    handler = FakeAlertHandler()
    d = Dispatcher([handler])
    p1 = _make_payload(score=_make_score(rules=["FEE_SPIKE"]))
    p2 = _make_payload(score=_make_score(rules=["LARGE_SOL_TRANSFER"]))
    # same event (same make_event defaults → same event_id), different rules
    d.dispatch(p1)
    d.dispatch(p2)
    assert len(handler.received) == 2


def test_dispatcher_fresh_instance_clears_dedup():
    handler = FakeAlertHandler()
    payload = _make_payload()
    d1 = Dispatcher([handler])
    d1.dispatch(payload)
    d2 = Dispatcher([handler])
    d2.dispatch(payload)    # new instance — should dispatch again
    assert len(handler.received) == 2


def test_handler_failure_continues():
    class BrokenHandler(AlertHandler):
        name = "BrokenHandler"
        def send(self, payload):
            raise RuntimeError("boom")

    good = FakeAlertHandler()
    d = Dispatcher([BrokenHandler(), good])
    d.dispatch(_make_payload())
    assert len(good.received) == 1


def test_logging_handler_sends(caplog):
    with caplog.at_level(logging.WARNING):
        handler = LoggingAlertHandler()
        handler.send(_make_payload())
    assert any("SENTINEL" in r.message or "HIGH" in r.message or "test alert" in r.message
               for r in caplog.records)


def test_file_handler_writes_jsonl(tmp_path):
    alert_file = tmp_path / "alerts.jsonl"
    handler = FileAlertHandler(str(alert_file))
    handler.send(_make_payload())
    lines = alert_file.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert "event_id" in data
    assert "score" in data


def test_file_handler_decimal_as_string(tmp_path):
    alert_file = tmp_path / "alerts.jsonl"
    handler = FileAlertHandler(str(alert_file))
    payload = _make_payload(event=make_event(fee_sol=Decimal("0.000005")))
    handler.send(payload)
    line = alert_file.read_text().strip()
    data = json.loads(line)
    # Decimal must be a string, not float
    assert data["fee_sol"] == "5E-6" or "e" in data["fee_sol"].lower() or data["fee_sol"] == "0.000005"
    # Must be parseable back to exact Decimal
    assert Decimal(data["fee_sol"]) == Decimal("0.000005")


def test_file_handler_failure_continues(tmp_path, caplog):
    handler = FileAlertHandler("/nonexistent_dir/alerts.jsonl")
    with caplog.at_level(logging.ERROR):
        handler.send(_make_payload())    # should not raise
    assert any("FileAlertHandler" in r.message or "failed" in r.message.lower()
               for r in caplog.records)
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_sentinel_dispatcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.dispatcher'`

- [ ] **Step 3: Implement `dispatcher.py`**

```python
# src/ai_accountant/sentinel/dispatcher.py
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from decimal import Decimal

from ai_accountant.sentinel.models import AlertPayload

logger = logging.getLogger(__name__)


class AlertHandler(ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def send(self, payload: AlertPayload) -> None: ...


class Dispatcher:
    def __init__(self, handlers: list[AlertHandler]) -> None:
        self._handlers = handlers
        self._seen: set[tuple[str, frozenset[str]]] = set()

    def dispatch(self, payload: AlertPayload) -> None:
        key = (payload.event.event_id, frozenset(payload.score.triggered_rules))
        if key in self._seen:
            logger.debug("Duplicate alert skipped: event_id=%s", payload.event.event_id)
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


class LoggingAlertHandler(AlertHandler):
    def send(self, payload: AlertPayload) -> None:
        level = logging.CRITICAL if payload.severity == "CRITICAL" else logging.WARNING
        logging.getLogger(__name__).log(
            level,
            "SENTINEL ALERT | %s | event_id=%s | wallet=%s | score=%d | rules=%s",
            payload.summary,
            payload.event.event_id,
            payload.event.wallet_address,
            payload.score.score,
            ",".join(payload.score.triggered_rules),
        )


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def _payload_to_dict(payload: AlertPayload) -> dict:
    e, s = payload.event, payload.score
    return {
        "event_id": e.event_id,
        "signature": e.signature,
        "wallet_address": e.wallet_address,
        "timestamp": e.timestamp,
        "transaction_type": e.transaction_type,
        "source": e.source,
        "fee_sol": str(e.fee_sol),
        "fee_paid_by_wallet": e.fee_paid_by_wallet,
        "native_in_sol": str(e.native_in_sol),
        "native_out_sol": str(e.native_out_sol),
        "native_net_sol": str(e.native_net_sol),
        "direction": e.direction,
        "status": e.status,
        "score": s.score,
        "risk_level": s.risk_level,
        "triggered_rules": s.triggered_rules,
        "reasons": s.reasons,
        "severity": payload.severity,
        "summary": payload.summary,
        "recommended_action_url": payload.recommended_action_url,
    }


class FileAlertHandler(AlertHandler):
    def __init__(self, path: str) -> None:
        self._path = path

    def send(self, payload: AlertPayload) -> None:
        try:
            line = json.dumps(_payload_to_dict(payload), cls=_DecimalEncoder)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            logger.error("FileAlertHandler failed to write alert: %s", exc, exc_info=True)
```

- [ ] **Step 4: Uncomment the `AlertHandler` import in `tests/conftest.py` and make `FakeAlertHandler` extend it**

Update the `FakeAlertHandler` class in `conftest.py`:

```python
# tests/conftest.py (FakeAlertHandler section)
from ai_accountant.sentinel.dispatcher import AlertHandler   # now importable

class FakeAlertHandler(AlertHandler):
    """Captures AlertPayload objects for test assertions."""
    def __init__(self) -> None:
        self.received: list = []

    def send(self, payload) -> None:
        self.received.append(payload)
```

- [ ] **Step 5: Run dispatcher tests**

```
pytest tests/test_sentinel_dispatcher.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/sentinel/dispatcher.py tests/test_sentinel_dispatcher.py tests/conftest.py
git commit -m "feat(sentinel): AlertHandler ABC, Dispatcher, LoggingAlertHandler, FileAlertHandler"
```

---

## Task 10: Flask app factory

**Files:**
- Create: `src/ai_accountant/sentinel/app.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add `test_app` helper to conftest**

```python
# append to tests/conftest.py
from ai_accountant.sentinel.app import create_app


def make_test_client(config=None, handlers=None):
    """Return a Flask test_client for integration tests."""
    if config is None:
        config = make_config()
    if handlers is None:
        handlers = [FakeAlertHandler()]
    return create_app(config, handlers).test_client(), handlers[0]
```

- [ ] **Step 2: Write failing integration tests**

```python
# tests/test_sentinel_integration.py
import hashlib
import hmac
import json
import pytest
from decimal import Decimal
from ai_accountant.sentinel.config import AuthConfig, AlertConfig
from conftest import make_config, make_test_client, VALID_WALLET, VALID_WALLET_2, UNKNOWN_WALLET

SECRET = "integration-test-secret"


def _tx(sig="sig1", from_=VALID_WALLET, to=UNKNOWN_WALLET, amount=15_000_000_000):
    return {
        "signature": sig, "slot": 1, "timestamp": 1700000000,
        "type": "TRANSFER", "source": "SYSTEM_PROGRAM",
        "fee": 5000, "feePayer": from_,
        "nativeTransfers": [{"fromUserAccount": from_, "toUserAccount": to, "amount": amount}],
        "tokenTransfers": [],
    }


def test_healthz():
    client, _ = make_test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_full_pipeline_alert_triggered():
    client, handler = make_test_client(
        config=make_config(alerts=AlertConfig(min_alert_score=0))
    )
    resp = client.post("/webhook", json=[_tx()])
    assert resp.status_code == 200
    assert len(handler.received) == 1


def test_full_pipeline_below_threshold():
    client, handler = make_test_client(
        config=make_config(alerts=AlertConfig(min_alert_score=100))
    )
    resp = client.post("/webhook", json=[_tx()])
    assert resp.status_code == 200
    assert len(handler.received) == 0


def test_unknown_wallet_no_alert():
    # Only UNKNOWN_WALLET in monitored_wallets, but VALID_WALLET sends the tx
    client, handler = make_test_client(
        config=make_config(
            monitored_wallets=frozenset({UNKNOWN_WALLET}),
            alerts=AlertConfig(min_alert_score=0),
        )
    )
    # Transaction involves VALID_WALLET → UNKNOWN_WALLET
    # UNKNOWN_WALLET receives SOL → will produce an event for UNKNOWN_WALLET
    # but VALID_WALLET is not monitored so no event for VALID_WALLET
    resp = client.post("/webhook", json=[_tx()])
    assert resp.status_code == 200
    # UNKNOWN_WALLET has incoming movement — event IS produced for it
    # This tests no error, not necessarily 0 alerts
    # To test truly no monitored wallet involved:
    tx_no_monitored = {
        "signature": "no-match", "slot": 1, "timestamp": 1700000000,
        "type": "TRANSFER", "source": "SYSTEM_PROGRAM",
        "fee": 5000, "feePayer": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
        "nativeTransfers": [
            {"fromUserAccount": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
             "toUserAccount": "So11111111111111111111111111111111111111112",
             "amount": 1_000_000_000}
        ],
        "tokenTransfers": [],
    }
    client2, handler2 = make_test_client(
        config=make_config(alerts=AlertConfig(min_alert_score=0))
    )
    resp2 = client2.post("/webhook", json=[tx_no_monitored])
    assert resp2.status_code == 200
    assert len(handler2.received) == 0


def test_malformed_json_returns_400():
    client, _ = make_test_client()
    resp = client.post(
        "/webhook",
        data=b"not json at all",
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_no_op_event_no_alert():
    # Failed tx, wallet paid fee but amount is below FAILED_HIGH_FEE threshold
    tx = {
        "signature": "failed-noop", "slot": 1, "timestamp": 1700000000,
        "type": "SWAP", "source": "JUPITER",
        "fee": 5000, "feePayer": VALID_WALLET,
        "nativeTransfers": [], "tokenTransfers": [],
        "transactionError": {"InstructionError": [0, "Custom 6000"]},
    }
    client, handler = make_test_client(
        config=make_config(alerts=AlertConfig(min_alert_score=50))
    )
    resp = client.post("/webhook", json=[tx])
    assert resp.status_code == 200
    assert len(handler.received) == 0


def test_auth_rejects_bad_signature():
    client, handler = make_test_client(
        config=make_config(
            auth=AuthConfig(enabled=True, type="header", secret=SECRET),
            alerts=AlertConfig(min_alert_score=0),
        )
    )
    resp = client.post("/webhook", json=[_tx()],
                       headers={"Authorization": "wrong-secret"})
    assert resp.status_code == 401
    assert len(handler.received) == 0


def test_two_monitored_wallets_same_tx():
    tx = _tx(from_=VALID_WALLET, to=VALID_WALLET_2, amount=1_000_000_000)
    client, handler = make_test_client(
        config=make_config(
            monitored_wallets=frozenset({VALID_WALLET, VALID_WALLET_2}),
            alerts=AlertConfig(min_alert_score=0),
        )
    )
    resp = client.post("/webhook", json=[tx])
    assert resp.status_code == 200
    wallets = {p.event.wallet_address for p in handler.received}
    assert wallets == {VALID_WALLET, VALID_WALLET_2}


def test_no_monitored_wallet_in_tx():
    tx = {
        "signature": "no-monitored", "slot": 1, "timestamp": 1700000000,
        "type": "TRANSFER", "source": "SYSTEM_PROGRAM",
        "fee": 5000, "feePayer": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
        "nativeTransfers": [
            {"fromUserAccount": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
             "toUserAccount": "So11111111111111111111111111111111111111112",
             "amount": 1_000_000_000},
        ],
        "tokenTransfers": [],
    }
    client, handler = make_test_client(
        config=make_config(alerts=AlertConfig(min_alert_score=0))
    )
    resp = client.post("/webhook", json=[tx])
    assert resp.status_code == 200
    assert len(handler.received) == 0
```

- [ ] **Step 3: Run to verify failure**

```
pytest tests/test_sentinel_integration.py::test_healthz -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.sentinel.app'`

- [ ] **Step 4: Implement `app.py`**

```python
# src/ai_accountant/sentinel/app.py
from __future__ import annotations

import logging
from typing import Any

from flask import Flask, abort, request

from ai_accountant.sentinel.auth import authenticate_request
from ai_accountant.sentinel.config import SentinelConfig
from ai_accountant.sentinel.dispatcher import (
    AlertHandler, Dispatcher, FileAlertHandler, LoggingAlertHandler,
)
from ai_accountant.sentinel.engine import score_event
from ai_accountant.sentinel.models import AlertPayload, AnomalyScore, WatchedEvent
from ai_accountant.sentinel.normalizer import normalize

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {
    "low":      "INFO",
    "medium":   "WARNING",
    "high":     "HIGH",
    "critical": "CRITICAL",
}


def _build_summary(event: WatchedEvent, score: AnomalyScore) -> str:
    parts = [f"[{score.risk_level.upper()}]"]
    if event.transaction_type:
        parts.append(event.transaction_type)
    if event.native_out_sol > 0:
        parts.append(f"{event.native_out_sol} SOL out")
    if event.native_in_sol > 0:
        parts.append(f"{event.native_in_sol} SOL in")
    if score.triggered_rules:
        parts.append(f"rules={','.join(score.triggered_rules)}")
    return " | ".join(parts)


def _build_alert_payload(event: WatchedEvent, score: AnomalyScore) -> AlertPayload:
    return AlertPayload(
        event=event,
        score=score,
        severity=_SEVERITY_MAP.get(score.risk_level, "WARNING"),
        summary=_build_summary(event, score),
        recommended_action_url=None,
    )


def _build_handlers(config: SentinelConfig) -> list[AlertHandler]:
    handlers: list[AlertHandler] = []
    for name in config.alerts.enabled_handlers:
        if name == "logging":
            handlers.append(LoggingAlertHandler())
        elif name == "file":
            handlers.append(FileAlertHandler(config.alerts.file_alert_path))
        else:
            logger.warning("Unknown handler name in config: %r — skipped", name)
    return handlers


def create_app(
    config: SentinelConfig,
    handlers: list[AlertHandler] | None = None,
) -> Flask:
    """
    Create and return the Flask application.

    handlers: if None, built from config.alerts.enabled_handlers.
              Pass an explicit list in tests (e.g. [FakeAlertHandler()]).
    """
    if handlers is None:
        handlers = _build_handlers(config)

    app = Flask(__name__)
    dispatcher = Dispatcher(handlers)
    app.extensions["sentinel_dispatcher"] = dispatcher
    app.extensions["sentinel_config"] = config

    @app.before_request
    def verify_auth() -> Any:
        if request.path == "/healthz":
            return None
        if not authenticate_request(request, config):
            abort(401)
        return None

    @app.post("/webhook")
    def webhook() -> Any:
        if not request.is_json:
            abort(400)
        body = request.get_json(silent=True)
        if body is None:
            abort(400)

        events = normalize(body, config.monitored_wallets)
        for event in events:
            s = score_event(config, event)
            if s.score < config.alerts.min_alert_score:
                continue
            dispatcher.dispatch(_build_alert_payload(event, s))

        return "", 200

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Run integration tests**

```
pytest tests/test_sentinel_integration.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 6: Run the full test suite**

```
pytest -v
```

Expected: all tests across all files PASS (including existing `test_solana_data_fetcher.py`).

- [ ] **Step 7: Commit**

```
git add src/ai_accountant/sentinel/app.py tests/test_sentinel_integration.py tests/conftest.py
git commit -m "feat(sentinel): Flask app factory, /webhook, /healthz, alert payload builder"
```

---

## Task 11: Sentinel `__init__.py` exports + example config

**Files:**
- Modify: `src/ai_accountant/sentinel/__init__.py`
- Create: `sentinel_config.example.toml`

- [ ] **Step 1: Wire up sentinel `__init__.py`**

```python
# src/ai_accountant/sentinel/__init__.py
"""
ai_accountant.sentinel — real-time Helius webhook monitoring.

Install the optional dep first: pip install -e ".[sentinel]"
"""
from ai_accountant.sentinel.app import create_app
from ai_accountant.sentinel.config import load_config
from ai_accountant.sentinel.dispatcher import AlertHandler

__all__ = ["create_app", "load_config", "AlertHandler"]
```

- [ ] **Step 2: Verify public surface is importable**

```
python -c "from ai_accountant.sentinel import create_app, load_config, AlertHandler; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Create the annotated example config**

```toml
# sentinel_config.example.toml
# Copy this file to sentinel_config.toml and edit before running the sentinel.
# Requires Python >= 3.11 for TOML; use sentinel_config.json on Python 3.10.
#
# Load with: cfg = load_config("sentinel_config.toml")

# ── Core ────────────────────────────────────────────────────────────────────

# "local" | "test" | "production"
# In production, auth.enabled MUST be true (enforced at startup).
environment = "local"

# Solana wallet addresses to monitor. At least one required.
monitored_wallets = [
    "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY",
]

# ── Authentication ───────────────────────────────────────────────────────────
[auth]
enabled = true
# "header": Helius sends the secret in the Authorization header (current default).
# "hmac":   Helius sends HMAC-SHA256(body, secret) in hex.
type = "header"
# Use "env:VAR_NAME" to read the secret from an environment variable.
secret = "env:SENTINEL_WEBHOOK_SECRET"

# ── Thresholds ───────────────────────────────────────────────────────────────
[thresholds]
# SOL outgoing in one tx that triggers LARGE_SOL_TRANSFER (score +40).
large_transfer_sol = "10.0"
# Fee above this triggers FEE_SPIKE (score +20).
max_fee_sol = "0.01"
# Fee on a failed tx above this triggers FAILED_HIGH_FEE (score +15).
failed_tx_fee_sol = "0.001"
# Distinct outgoing token mints above this triggers MASS_TOKEN_DRAIN (score +50).
mass_drain_token_count = 3

# ── Rules ────────────────────────────────────────────────────────────────────
[rules]
check_large_sol_transfer = true
check_known_bad_program  = true
check_mass_token_drain   = true
check_fee_spike          = true
check_failed_high_fee    = true
# Opt-in: tracks counterparties in memory; state resets on process restart.
check_new_counterparty   = false

# Add known malicious program or wallet addresses here.
blacklisted_programs = []

# ── Alerts ───────────────────────────────────────────────────────────────────
[alerts]
# Alert only when score >= this value (0 = alert on everything).
min_alert_score = 50

# Active output handlers. Valid values: "logging", "file"
# "logging" → Python logging (always safe, no extra config).
# "file"    → JSON-lines file at file_alert_path.
# Sprint 2/3 will add "telegram", "discord", "web_push".
enabled_handlers = ["logging"]

# Minimum Python logging level for the logging handler.
log_level = "WARNING"

# Path for the "file" handler. Ignored unless "file" is in enabled_handlers.
file_alert_path = "sentinel_alerts.jsonl"
```

- [ ] **Step 4: Run full test suite one final time**

```
pytest -v
```

Expected: all tests PASS, 0 failures.

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/sentinel/__init__.py sentinel_config.example.toml
git commit -m "feat(sentinel): public __init__ exports and annotated example config"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Helius webhook POST receiver | Task 10 (`app.py` `/webhook`) |
| HMAC/header auth, fail closed | Task 4 (`auth.py`), Task 3 validation |
| Event normalization → `WatchedEvent` | Task 5–6 (`normalizer.py`) |
| `event_id` deterministic hash | Task 5 |
| `direction` field | Task 5 |
| Reuse of `_build_transaction_row` (with tech debt note) | Task 6 (`_get_fetcher`, `_NoOpSession`) |
| One tx → multiple events for multiple wallets | Task 6 (`normalize` loop) |
| Unknown wallets not an error | Task 6 (skip silently) |
| Malformed tx skipped, rest continues, count+sigs logged | Task 6 |
| All 6 anomaly rules | Tasks 7–8 |
| `RuleResult.reason` non-None filtering in `reasons` | Task 7 (`score_event`) |
| Risk level bands | Task 7 |
| Score clamped to 100 | Task 7 |
| `AlertHandler` ABC | Task 9 |
| `Dispatcher` in-process deduplication | Task 9 |
| Handler failure isolation | Task 9 |
| `LoggingAlertHandler` | Task 9 |
| `FileAlertHandler` with Decimal-as-string + failure isolation | Task 9 |
| `create_app` as only Flask entry point, no global app | Task 10 |
| `/healthz` no external calls, auth-exempt | Task 10 |
| `enabled_handlers` single control for outputs | Task 9, 10 |
| `file_alert_path` ignored unless `"file"` in handlers | Task 9, 11 |
| Config validation: all 10 rules | Task 3 |
| TOML / JSON loading | Task 3 |
| Unknown config keys rejected | Task 3 |
| `sentinel` optional dep | Task 1 |
| `sentinel __init__` does not affect existing imports | Task 1, 11 |
| Integration tests via `test_client()` | Task 10 |
| Two-wallet integration test | Task 10 |
| No-monitored-wallet integration test | Task 10 |
| Example config file | Task 11 |

**Placeholder scan:** No TBD/TODO present. All code blocks are complete.

**Type consistency check:** `WatchedEvent.movements_in/out` are `tuple` throughout (Task 2 models, Task 6 normalizer `tuple(row[...])`, Task 8 engine iterates with `list(event.movements_in)`). `frozenset[str]` used consistently for `monitored_wallets` and `blacklisted_programs`. `Decimal` used throughout; no `float` introduced in financial paths.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-03-sentinel-core.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

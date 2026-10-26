# Academic AI Compute Fabric — Token Usage & Quota Service (TUQS)
### Module 8 · Task Impl-1: AI-Assisted Implementation & Foundation Build

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Testing](https://img.shields.io/badge/Pytest-81%20Passed%20%7C%200%20Skipped-brightgreen.svg)](docs/test-evidence-impl1.txt)
[![Architecture](https://img.shields.io/badge/Architecture-Hexagonal%20%2F%20Ports%20%26%20Adapters-orange.svg)](#3-architecture--project-layout)
[![Governance](https://img.shields.io/badge/BMad-Full%20Ceremony%20Build-purple.svg)](docs/sprint-status.yaml)

---

## 1. Project Overview

The **Token Usage & Quota Service (TUQS)** meters token consumption for the university AI compute fabric. It records every consumption event in an append-only ledger, keeps a per-user daily counter, warns when a user reaches 80% of the daily limit, and denies admission once a request would exceed 100%.

### Team Members
- **Alexis Delgado** — *Lead Architect*
- **Valentina Gómez** — *Test Lead*

---

## 2. Core Implemented Stories (Task Impl-1)

1. **Story 8.1 — Token Consumption Event Ingestion & Ledger Recording** · `POST /api/v1/tokens/events` → `201`
   - Requires `user_id`, `subject_id` and integer `prompt_tokens` / `completion_tokens`.
   - In one database transaction: provisions the daily `user_quotas` row if absent, increments `tokens_used` in the database (`tokens_used = tokens_used + n`) and appends a `token_ledger` row.
   - Returns the cumulative usage and remaining balance.

2. **Story 8.2 — Soft-Warning Header at 80% Quota Threshold** · events, `GET /api/v1/tokens/balance/{user_id}`, check-allowance
   - While usage ≥ 80%: body `warning.status = "QUOTA_WARNING_80_PERCENT"` with `remaining_tokens_before_denial`, and header `X-Quota-Warning: 80` (PRD FR-11).
   - Every quota response also carries `X-Quota-Remaining` and `X-Quota-Reset`.

3. **Story 8.3 — Hard Denial Enforcement at 100% Quota Ceiling** · `POST /api/v1/tokens/check-allowance` → `200`
   - `allowed = tokens_used + requested_tokens <= token_limit` (zero tolerance).
   - No upper bound on `requested_tokens`; a denial returns `reason_code: "DAILY_QUOTA_EXCEEDED"`, `reason: "Daily token quota exhausted; resets at 00:00 UTC"` and `resets_at` (next 00:00 UTC).

4. **Scaffold** — 32-node simulated fleet (31 × 24 GB workstations + 1 server × 2 × 48 GB = 840 GB VRAM), `GET /api/v1/health`, `GET /api/v1/fleet`, Alembic migrations, uniform error envelope.

The API contract is [`docs/contracts/openapi.yaml`](docs/contracts/openapi.yaml); `tests/contract/` fails if the running app drifts from it.

---

## 3. Architecture & Project Layout

Ports & Adapters, dependencies pointing inward:

```text
academic-ai-compute-tuqs/
├── alembic.ini · migrations/           # Alembic env + 0001 (tables + CHECKs) + 0002 (BIGINT counters)
├── docs/
│   ├── prd.md                          # Scoped module PRD
│   ├── contracts/openapi.yaml          # Impl-1 OpenAPI 3.1 contract (enforced by test)
│   ├── contracts/solu2/                # Solu-2 contracts, archived for Impl-2
│   ├── sprint-status.yaml              # BMad sprint tracking with status history
│   ├── ai-decision-log.md              # 11 AI interactions, incl. rejected/corrected outputs
│   ├── walkthrough-impl1.md            # Implementation walkthrough report
│   └── test-evidence-impl1.txt         # Raw pytest -v and ruff output
├── src/
│   ├── main.py                         # FastAPI app, lifespan (auto-migration), error handlers
│   ├── config.py                       # Pydantic Settings
│   ├── composition.py                  # Composition root: binds adapters to ports
│   ├── domain/                         # Pure business rules (no framework imports)
│   ├── application/                    # Use cases: IngestTokenEvent, GetQuotaBalance, CheckAllowance
│   ├── ports/                          # IQuotaRepository, IClock, IFleetProvider
│   └── adapters/
│       ├── inbound/                    # FastAPI router, DTOs, ErrorBody handlers
│       └── outbound/                   # SQLAlchemy repository, migrations runner, clock, fleet JSON
└── tests/
    ├── conftest.py                     # In-memory SQLite, FakeClock, seed factories
    ├── fixtures/                       # fleet_nodes.json, seed_quotas.json, seed_users.json, fake_clock.py
    ├── unit/                           # BDD story tests, domain tests, error handling, fleet/health
    ├── integration/                    # Concurrency (no lost updates), Alembic schema check
    └── contract/                       # OpenAPI contract vs running app
```

---

## 4. Quick Start

### Option A: Local (Python 3.11+)

```bash
cd academic-ai-compute-tuqs
pip install -e ".[dev]"
pytest
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

- `pytest` runs 81 tests deterministically (fixed `FakeClock`, in-memory database) and writes no files.
- On startup the service applies Alembic migrations to `DATABASE_URL` (default `sqlite:///./tuqs.db`). Set `AUTO_MIGRATE=false` to manage them yourself with `alembic upgrade head`.
- Docs: [http://localhost:8000/docs](http://localhost:8000/docs) · Health: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- Lint: `ruff check .`

### Option B: Docker Compose

```bash
docker compose up --build -d
curl http://localhost:8000/api/v1/health
docker compose down
```

The SQLite file lives in `./data/tuqs.db` (mounted volume), so data survives container recreation.

### Configuration

All variables are documented in [`.env.example`](.env.example): `DATABASE_URL`, `AUTO_MIGRATE`, `DEFAULT_DAILY_TOKEN_LIMIT` (100000), `SOFT_WARNING_THRESHOLD` (0.80), `LOG_LEVEL`, `FLEET_FIXTURE_PATH`.

---

## 5. API Reference & Sample Payloads

### Ingest a token event (Stories 8.1 & 8.2)
```http
POST /api/v1/tokens/events HTTP/1.1
Content-Type: application/json

{ "user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 500, "completion_tokens": 250 }
```
`201 Created` · headers `X-Quota-Remaining: 89250`, `X-Quota-Reset: 2026-10-26T00:00:00Z`
```json
{
  "id": "6f1c2a8e-4b7d-4c7e-9a51-3d2e8f0b9c11",
  "user_id": "sam",
  "subject_id": "CS-480",
  "prompt_tokens": 500,
  "completion_tokens": 250,
  "total_tokens": 750,
  "tokens_used": 10750,
  "token_limit": 100000,
  "remaining_balance": 89250,
  "warning": {
    "warning": false,
    "threshold": "80%",
    "status": null,
    "remaining_tokens_before_denial": 89250,
    "message": null
  },
  "timestamp": "2026-10-25T12:00:00Z"
}
```

### Check allowance (Story 8.3)
```http
POST /api/v1/tokens/check-allowance HTTP/1.1
Content-Type: application/json

{ "user_id": "sam", "requested_tokens": 500 }
```
`200 OK` when exhausted · header `X-Quota-Warning: 80`
```json
{
  "allowed": false,
  "reason": "Daily token quota exhausted; resets at 00:00 UTC",
  "reason_code": "DAILY_QUOTA_EXCEEDED",
  "requested_tokens": 500,
  "remaining_balance": 0,
  "tokens_used": 100000,
  "token_limit": 100000,
  "resets_at": "2026-10-26T00:00:00Z"
}
```

### Errors
Every non-2xx response uses one envelope and echoes `X-Correlation-ID`:
```json
{
  "error_code": "ERR_INVALID_TOKEN_COUNT",
  "message": "Total tokens for an event must be strictly greater than zero",
  "correlation_id": "req-123",
  "timestamp": "2026-10-25T12:00:00Z",
  "details": null
}
```
Codes: `ERR_INVALID_TOKEN_COUNT` (400), `ERR_VALIDATION` (422), `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_STORAGE_UNAVAILABLE` (503 + `Retry-After: 5`, on reads and writes), `ERR_INTERNAL` (500). A client `X-Correlation-ID` is echoed only if it matches `[A-Za-z0-9._-]{1,128}`.

---

## 6. Test Suite & Quality Evidence

```bash
pytest
pytest --cov=src --cov-branch
ruff check .
```

```text
============================= 81 passed ==============================
All checks passed!
TOTAL coverage of src/ (lines + branches): 95%
```

Full output: [`docs/test-evidence-impl1.txt`](docs/test-evidence-impl1.txt). Known limitations are listed in the [walkthrough](docs/walkthrough-impl1.md#6-known-limitations).

# Implementation Walkthrough Report (Task Impl-1)

**Module:** Module 8 — Token Usage & Quota Service (TUQS)  
**Parent Subsystem:** Academic AI Compute Fabric  
**Course Activity:** Task Impl-1: AI-Assisted Implementation & Foundation Build  
**Authors:** Alexis Delgado (Lead Architect) & Valentina Gómez (Test Lead)  
**Date:** October 25, 2026  
**Quality Gate:** 81/81 tests passed, 0 skipped, 0 failed · `ruff check .` clean · 95% line+branch coverage of `src/`  
**Revised:** 2026-10-26 after `bmad-code-review` (see §7)

---

## 1. Architecture Overview

TUQS is a FastAPI service organised as Ports & Adapters. Dependencies point inward only:

```text
HTTP (FastAPI)            application              domain (pure Python)
adapters/inbound  ─────►  use_cases.py  ─────────► models.py, services.py
   router.py                  │                      exceptions.py
   errors.py                  ▼
   schemas.py              ports/  (IQuotaRepository, IClock, IFleetProvider)
                              ▲
adapters/outbound ────────────┘  sql_repository.py, db.py, migrations.py,
                                 system_clock.py, fleet_adapter.py
composition.py: the only module that binds adapters to ports (FastAPI providers)
```

- `src/domain/` has no FastAPI, SQLAlchemy or HTTP imports.
- `src/application/use_cases.py` holds one use case per story (`IngestTokenEvent`, `GetQuotaBalance`, `CheckAllowance`) and depends only on ports.
- `src/adapters/inbound/router.py` only maps DTOs to commands and sets quota headers.
- `src/composition.py` exposes `get_clock`, `get_repository`, `get_fleet_provider` and the use-case providers; tests override `get_clock` with `FakeClock` and `get_db` with an in-memory database.

### Directory layout

```text
academic-ai-compute-tuqs/
├── README.md · Dockerfile · docker-compose.yml · .env.example · pyproject.toml
├── alembic.ini · migrations/            # Alembic env + revisions 0001 (schema) and 0002 (BIGINT counters)
├── docs/
│   ├── prd.md                           # Module PRD (Plan-2)
│   ├── contracts/openapi.yaml           # Impl-1 contract (OpenAPI 3.1, enforced by test)
│   ├── contracts/solu2/                 # Solu-2 contract + (P, Q, I) contracts, archived for Impl-2
│   ├── sprint-status.yaml · ai-decision-log.md · walkthrough-impl1.md
│   └── test-evidence-impl1.txt          # Raw pytest -v and ruff output
├── src/
│   ├── main.py · config.py · composition.py
│   ├── domain/ (models, services, exceptions)
│   ├── application/use_cases.py
│   ├── ports/ (repository, clock, fleet)
│   └── adapters/inbound (router, schemas, errors) · adapters/outbound (db, sql_repository,
│       migrations, system_clock, fleet_adapter)
└── tests/
    ├── conftest.py                      # In-memory DB, FakeClock, seed factories
    ├── fixtures/                        # fleet_nodes.json (32 nodes), seed_quotas.json, seed_users.json, fake_clock.py
    ├── unit/                            # BDD story tests, domain tests, error handling, fleet/health
    ├── integration/                     # Concurrency on file-backed SQLite, Alembic schema check
    └── contract/                        # OpenAPI contract vs running app
```

### Database (Alembic revisions `0001` + `0002`)

| Table | Columns | Constraints |
|---|---|---|
| `user_quotas` | `id, user_id, date, tokens_used, token_limit` (counters BIGINT) | `UNIQUE(user_id, date)`, `tokens_used >= 0`, `token_limit > 0` |
| `token_ledger` | `id, user_id, subject_id, prompt_tokens, completion_tokens, total_tokens, timestamp` (counters BIGINT) | `prompt/completion >= 0`, `total = prompt + completion`, `total > 0`, index `(user_id, timestamp)` |

`tests/integration/test_migrations.py` checks with Alembic `compare_metadata` that the migrated schema equals the ORM metadata.

---

## 2. Reconciliation with Solu-2

Impl-1 implements the three Module 8 stories recommended in the Annex. Their schema (`user_quotas`, `token_ledger`) is a simplification of the Solu-2 DDL (`allocation`, `bucket`, `reservation`, `usage_event`).

| Impl-1 (Annex) | Closest Solu-2 backlog item | What is deferred to Impl-2 |
|---|---|---|
| 8.1 Ledger ingestion | Story 2.1 Usage Settlement & Ledger Recording | Reservation link, GPU-seconds, idempotency key (AD-2) |
| 8.2 80% soft warning | Story 3.3 80% Soft Warning Outbox | Notification outbox and once-per-period de-duplication |
| 8.3 Hard denial | Story 1.3 Explainable Denial Decision Engine | Group/course buckets, ordered row locks, CLAMP policy |

The Solu-2 OpenAPI file and formal contracts are kept unchanged in `docs/contracts/solu2/`. The active contract `docs/contracts/openapi.yaml` describes only what the service exposes today.

### Invariants honoured in this slice (ARCHITECTURE.md v2.0)

| Invariant | Enforcement | Verified by |
|---|---|---|
| AD-1 one transaction | `record_consumption`: insert-if-absent, `UPDATE … SET tokens_used = tokens_used + :n RETURNING`, ledger insert, one commit | `test_concurrent_events_do_not_lose_updates`, `test_failed_ledger_insert_rolls_back_counter` |
| AD-3 bounded counters / no over-grant | `UserQuota.can_consume`: `tokens_used + requested <= token_limit`; DB `CHECK tokens_used >= 0` | Story 8.3 boundary tests, domain parametrised tests |
| AD-4 append-only ledger reconciles | Ledger rows are only inserted; counter equals the sum of ledger deltas | Concurrency test asserts `counter == SUM(total_tokens)` |
| AD-5 single time source | Each use case reads `IClock` once; timestamp, UTC period key and `resets_at` derive from that instant. Daily periods are UTC days (Annex), superseding AD-5's `America/Bogota` key for Impl-1 | `test_story_8_3_new_day_resets_allowance`, `test_period_key_and_reset_come_from_the_same_instant` |
| AD-6 explained denials | `reason_code = DAILY_QUOTA_EXCEEDED` + human-readable `reason` | Story 8.3 tests |
| AD-7 fail closed | `OperationalError` on writes **and reads** → `StorageUnavailableError` → 503 + `Retry-After: 5`; nothing recorded | `test_storage_unavailable_fails_closed_with_503`, `test_read_paths_fail_closed_on_real_database_error` |

---

## 3. The 3 Core Stories

### Ceremony justification (Two-Sentence Rule)

None of the three stories can be stated as a compact change: each one creates or changes a shared table (`user_quotas`, `token_ledger`), a public endpoint consumed by inference gateways, and a cross-cutting invariant (AD-1, AD-3, AD-6), so the blast radius covers every downstream module that meters or admits tokens. Their verification needs concurrency, boundary and contract tests rather than a single assertion. Full Ceremony was therefore mandatory, as the task statement also notes.

### 6-step build sequence as applied

| Step | Story 8.1 | Story 8.2 | Story 8.3 |
|---|---|---|---|
| 1. Context ingestion | Annex 8.1, PRD, AD-1/AD-4 | Annex 8.2, PRD FR-11 | Annex 8.3, PRD FR-12, AD-3/AD-6 |
| 2. Repository inspection | Ports & Adapters layout from Solu-2 `ports-and-adapters.md` | Existing `QuotaDomainService` | Existing `UserQuota` model |
| 3. Task breakdown | Domain entry → port → SQL adapter → use case → endpoint → tests | Threshold rule → headers → tests | Allowance rule → reason code → tests |
| 4. Code + tests together | Story tests + concurrency test | Story tests + boundary at 80.0% | Story tests + ±1 token boundaries |
| 5. DoD verification | `pytest`, `ruff check .` | same | same |
| 6. Review & status | Review found lost update (D-07) → rework → done | Header value corrected (D-04/D-08) → done | Error envelope, `reason_code` (D-09) → done |

### Story 8.1 — Token Consumption Event Ingestion & Ledger Recording
* **Goal:** ingest prompt/completion token counts, increment the daily counter atomically, append an immutable ledger entry, return the remaining balance.
* **Endpoint:** `POST /api/v1/tokens/events` → `201 Created`; `400 ERR_INVALID_TOKEN_COUNT` (0 + 0 tokens); `422 ERR_VALIDATION` (missing `subject_id`, negative or > 1,000,000 tokens, non-integer JSON values, ids with whitespace); `503 ERR_STORAGE_UNAVAILABLE`.
* **Database changes:** row provisioned in `user_quotas` on the first event of the UTC day; `tokens_used` incremented in the database; one row appended to `token_ledger`.
* **Behaviour note:** metering records real consumption, so `tokens_used` may exceed `token_limit`; the overrun is logged (`quota_overrun`). Admission is enforced by Story 8.3.
* **BDD scenario:** Sam at 10,000/100,000 + event of 500 + 250 → ledger row of 750, `tokens_used = 10,750`, `remaining_balance = 89,250`.
* **Tests:** `tests/unit/test_story_8_1_ledger_ingestion.py` (13), `tests/integration/test_atomic_consumption.py` (2).

### Story 8.2 — Soft-Warning Header at 80% Quota Threshold
* **Goal:** warn when `tokens_used / token_limit >= 0.80`.
* **Endpoints:** `POST /api/v1/tokens/events`, `GET /api/v1/tokens/balance/{user_id}`, `POST /api/v1/tokens/check-allowance`.
* **Output:** body `warning = { warning: true, threshold: "80%", status: "QUOTA_WARNING_80_PERCENT", remaining_tokens_before_denial }`; headers `X-Quota-Warning: 80` (PRD FR-11), `X-Quota-Remaining`, `X-Quota-Reset`.
* **Database changes:** none (reads `user_quotas`). Balance queries never create rows.
* **BDD scenario:** Sam at 82,000/100,000 → `QUOTA_WARNING_80_PERCENT`, 18,000 tokens remaining, `X-Quota-Warning: 80`.
* **Tests:** `tests/unit/test_story_8_2_soft_warning.py` (9): 82%, crossing 79k→82k on ingestion, 75% (no warning), exactly 80%, header on allowance checks, read-only balance, seeded fixture quotas, path `user_id` validation.

### Story 8.3 — Hard Denial Enforcement at 100% Quota Ceiling
* **Goal:** deny any request with `tokens_used + requested > token_limit`.
* **Endpoint:** `POST /api/v1/tokens/check-allowance` → `200` with `allowed`, `reason`, `reason_code`, `requested_tokens`, `remaining_balance`, `tokens_used`, `token_limit`, `resets_at`; `422 ERR_VALIDATION` for `requested_tokens <= 0` or non-integer. No upper bound: any request above the remaining quota is an explained denial.
* **Database changes:** none (read-only).
* **BDD scenario:** Sam at 100,000/100,000 requesting 500 → `allowed: false`, `reason_code: DAILY_QUOTA_EXCEEDED`, `reason: "Daily token quota exhausted; resets at 00:00 UTC"`, `resets_at: 2026-10-26T00:00:00Z`.
* **Tests:** `tests/unit/test_story_8_3_hard_denial.py` (9): exhausted, within budget, exactly 100% allowed, +1 token denied, 0 and −100 rejected, new UTC day resets, read-only check, 1,500,000-token request denied with `DAILY_QUOTA_EXCEEDED`.

### Cross-cutting tests
* `tests/unit/test_domain_quota_service.py` (18): pure domain rules without FastAPI or a database.
* `tests/unit/test_error_handling.py` (11): `ErrorBody` on 404, correlation id echo and sanitising, 503 fail-closed on writes and on real read failures, error subclasses, failing clock, structured 500 without leaking internals.
* `tests/unit/test_settings.py` (6): invalid limit, threshold and log level fail at startup.
* `tests/contract/test_openapi_contract.py` (5): operations, status codes, payload schemas, required fields and bounds match `docs/contracts/openapi.yaml`.
* `tests/integration/test_migrations.py` (5): schema equals ORM, idempotent, BIGINT counters, upgrade 0001→0002 keeps rows, `%` in the URL. `tests/unit/test_fleet_and_health.py` (3).

---

## 4. Automated Test Runner Evidence

Full verbose output: [`docs/test-evidence-impl1.txt`](test-evidence-impl1.txt). Summary on 2026-10-26:

```text
platform win32 -- Python 3.12.6, pytest-9.0.3, pluggy-1.6.0
collected 81 items
tests/contract/test_openapi_contract.py        5 passed
tests/integration/test_atomic_consumption.py   2 passed
tests/integration/test_migrations.py           5 passed
tests/unit/test_domain_quota_service.py       18 passed
tests/unit/test_error_handling.py             11 passed
tests/unit/test_fleet_and_health.py            3 passed
tests/unit/test_settings.py                    6 passed
tests/unit/test_story_8_1_ledger_ingestion.py 13 passed
tests/unit/test_story_8_2_soft_warning.py      9 passed
tests/unit/test_story_8_3_hard_denial.py       9 passed
============================= 81 passed =============================

$ ruff check .
All checks passed!

$ pytest --cov=src --cov-branch
TOTAL    582 stmts   24 miss   42 branches   10 partial   95%
```

---

## 5. Hardware Simulation & Fleet Topology

`tests/fixtures/fleet_nodes.json` describes the 32 university nodes: 31 workstations × 1 GPU × 24 GB (744 GB) and 1 server × 2 GPUs × 48 GB (96 GB), 840 GB VRAM in total. `GET /api/v1/health` and `GET /api/v1/fleet` serve it through `IFleetProvider`; `tests/unit/test_fleet_and_health.py` checks the composition.

---

## 6. Known Limitations

* The service is verified on SQLite. The PostgreSQL path uses the same SQL (`ON CONFLICT DO NOTHING`, `UPDATE … RETURNING`) but no PostgreSQL driver is shipped and it is not tested in this sprint.
* `check-allowance` is advisory: it does not hold tokens, so two gateways can both be allowed before either reports consumption. Holds with TTL are the Solu-2 `reserveTokens` design, scheduled for Impl-2.
* No idempotency key on `POST /tokens/events` yet (AD-2): a retried event is counted twice.
* `seed_users.json` documents the personas; the service has no user table in this slice.
* No authentication or authorization on any endpoint; no request middleware for correlation ids on successful responses.
* The full list of deferred review items is in the BMad workspace (`_bmad-output/implementation-artifacts/deferred-work.md`).

---

## 7. BMad Code Review (2026-10-26)

`bmad-create-story` produced story files 8.1–8.3 retroactively, and `bmad-code-review` reviewed the whole implementation against them (Blind Hunter, Edge Case Hunter, Acceptance Auditor). Triage: 3 decision-needed, 11 patch, 9 deferred, 9 dismissed. All three BDD scenarios were confirmed as met.

| Decision | Resolution |
|---|---|
| Day boundary: 00:00 UTC (Annex) vs `America/Bogota` (AD-5) | Keep UTC; AD-5's period-key time zone is superseded for Impl-1 |
| Missing `subject_id` defaulted to `CS-480` | `subject_id` is required (422 when absent) |
| `requested_tokens` above 1,000,000 returned 422 | Upper bound removed; counters widened to BIGINT; oversize requests are explained denials |

The 11 patches (single clock read, BIGINT migration, fail-closed reads, strict integer token counts, id validation, correlation-id sanitising, error subclass mapping, handler clock fallback, settings validation, `%` in the database URL, dead-code removal) are in commits `84c640d`…`ddcb5b7`, each covered by a new test.

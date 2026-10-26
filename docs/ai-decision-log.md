# AI Governance & Implementation Decision Log (Impl-1)

**Module:** Module 8 — Token Usage & Quota Service (TUQS)  
**Parent Platform:** Academic AI Compute Management Platform (University AI Compute Fabric)  
**Engineering Leads:** Alexis Delgado (Lead Architect) & Valentina Gómez (Test Lead)  
**Date:** October 25, 2026  
**Standard:** BMad Full Ceremony AI Governance Level 3  

Invariant references (AD-n) follow `Planning/ARCHITECTURE.md` v2.0: AD-1 one transaction per
admission/write, AD-3 bounded counters, AD-4 append-only ledger that reconciles to counters,
AD-5 single time source and period keys, AD-6 every non-ALLOW decision explained, AD-7 fail closed.

---

## Summary of Decisions

| # | Step / Story | Persona / Agent | Human Owner | Decision | Reason & Invariant Upheld |
|---|---|---|---|---|---|
| **D-01** | Scaffolding | Amelia (bmad-agent-dev) | Alexis Delgado | **REJECT & OVERRIDE** | AI proposed raw SQLite queries inside the FastAPI router. Rejected in favor of Ports & Adapters with `SQLQuotaRepository`. |
| **D-02** | Story 8.1 | Amelia (bmad-agent-dev) | Valentina Gómez | **MODIFY** *(not effective, superseded by D-07)* | AI proposed separate read and write steps without an atomic transaction. The first fix kept a Python read-modify-write and two commits. |
| **D-03** | Story 8.1 | Amelia (bmad-agent-dev) | Alexis Delgado | **ACCEPT** | Approved Pydantic v2 DTO schema for `TokenEventRequest` with non-negative validation (`ge=0`). Upper bounds added later in D-09. |
| **D-04** | Story 8.2 | Amelia (bmad-agent-dev) | Valentina Gómez | **REJECT & OVERRIDE** *(value corrected in D-08)* | AI omitted the HTTP response header for the 80% soft warning. Forced injection of `X-Quota-Warning`. |
| **D-05** | Story 8.3 | Amelia (bmad-agent-dev) | Alexis Delgado | **MODIFY** | AI returned HTTP 403 with an empty body on exhaustion. Changed to 200 OK with `{ allowed: false, reason, reason_code }` and the UTC reset instant. |
| **D-06** | Test Architecture | Murat (bmad-tea) | Valentina Gómez | **ACCEPT** *(side effect fixed in D-10)* | Adopted in-memory SQLite with `StaticPool` and `dependency_overrides[get_db]` in `conftest.py`. |
| **D-07** | Story 8.1 — review | Claude Code (adversarial code review) | Alexis Delgado | **REJECT & REWRITE** | Concurrency probe proved lost updates. Increment moved into the database inside one transaction with the ledger append (AD-1, AD-4). |
| **D-08** | Contracts — review | Claude Code (adversarial code review) | Alexis Delgado | **REJECT & REWRITE** | `docs/contracts/openapi.yaml` described Solu-2 endpoints that Impl-1 does not expose. Replaced by an Impl-1 contract enforced by a test; Solu-2 contract archived. |
| **D-09** | Error handling — review | Claude Code (adversarial code review) | Alexis Delgado | **MODIFY** | Four different error shapes and a plain-text 500 on token overflow. Unified `ErrorBody` envelope and request bounds. |
| **D-10** | Architecture & tests — review | Claude Code (adversarial code review) | Alexis Delgado | **MODIFY** | Router built adapters and used the system clock directly; tests depended on the wall-clock date and created `tuqs.db`. Added application layer, composition root, injectable `IClock`, Alembic migrations. |

---

## Detailed Decision Entries

### Entry D-01: Rejection of Monolithic Controller in Scaffolding
- **Phase/Story:** Scaffolding & Architecture Setup
- **Persona/Skill:** Amelia (`bmad-agent-dev`)
- **Prompt (Summary):** "Generate FastAPI router and database models for Module 8 token usage tracking."
- **AI Output (Summary):** A single `main.py` where endpoints executed raw SQL cursors through `sqlite3.connect()`.
- **Human Decision:** **REJECT & OVERRIDE** (Decided by **Alexis Delgado**)
- **Technical Rationale:** Direct database access inside web controllers violates the Ports & Adapters structure fixed in Solu-2 (`ports-and-adapters.md`) and rubric dimension 1.
- **Adopted Design:** Domain models (`src/domain/models.py`), abstract ports (`src/ports/repository.py`), inbound controllers (`src/adapters/inbound/router.py`), outbound adapter (`src/adapters/outbound/sql_repository.py`).
- **Artifacts Changed:** `src/domain/models.py`, `src/ports/repository.py`, `src/adapters/inbound/router.py`, `src/adapters/outbound/sql_repository.py`.

---

### Entry D-02: Enforcing Atomic Increment for Token Event Ingestion (first attempt)
- **Phase/Story:** Story 8.1
- **Persona/Skill:** Amelia (`bmad-agent-dev`)
- **Prompt (Summary):** "Implement `POST /api/v1/tokens/events` to ingest prompt and completion tokens."
- **AI Output (Summary):** Read `tokens_used`, add `total_tokens` in Python, then issue an update: a classic lost-update race.
- **Human Decision:** **MODIFY** (Decided by **Valentina Gómez**)
- **Technical Rationale:** AD-1 requires the counter change and the ledger append to happen in one transaction.
- **Post-review status:** **Not effective.** The accepted change still read the value into Python, wrote the absolute total back, and committed the quota and the ledger separately. The defect was not caught because no test exercised concurrency. Corrected in **D-07**.

---

### Entry D-03: DTO Schema Validation for Ingestion Payload
- **Phase/Story:** Story 8.1
- **Persona/Skill:** Amelia (`bmad-agent-dev`)
- **Prompt (Summary):** "Define Pydantic v2 schemas for token ingestion request and response payloads."
- **AI Output (Summary):** `TokenEventRequest` with `user_id: str`, `prompt_tokens: int = Field(..., ge=0)`, `completion_tokens: int = Field(..., ge=0)`.
- **Human Decision:** **ACCEPT** (Decided by **Alexis Delgado**)
- **Technical Rationale:** Negative integers are blocked at the boundary with HTTP 422 before touching the database. The missing upper bound and `max_length` were added in D-09.
- **Artifacts Changed:** `src/adapters/inbound/schemas.py`.

---

### Entry D-04: Mandatory Injection of `X-Quota-Warning` Response Header
- **Phase/Story:** Story 8.2
- **Persona/Skill:** Amelia (`bmad-agent-dev`)
- **Prompt (Summary):** "Implement soft-warning evaluation when user consumption reaches or exceeds 80% of daily quota."
- **AI Output (Summary):** Returned `warning: true` in the JSON body but no HTTP header.
- **Human Decision:** **REJECT & OVERRIDE** (Decided by **Valentina Gómez**)
- **Technical Rationale:** The story is titled "Soft-Warning **Header** at 80% Quota Threshold", and PRD FR-11 (`Planning/prd.md`) requires `X-Quota-Warning: 80` and `X-Quota-Remaining` on every response while usage ≥ 80%. Gateways read headers without parsing bodies.
- **Correction (D-08 review):** The first implementation sent the value `QUOTA_WARNING_80_PERCENT` and only on two endpoints. The header now carries `80` (FR-11), `X-Quota-Remaining` and `X-Quota-Reset` are added, and all three quota endpoints set them. The body keeps `status: "QUOTA_WARNING_80_PERCENT"` as the Annex BDD scenario requires.
- **Artifacts Changed:** `src/adapters/inbound/router.py`, `tests/unit/test_story_8_2_soft_warning.py`.

---

### Entry D-05: Protocol Consistency on 100% Hard Denial Allowance Check
- **Phase/Story:** Story 8.3
- **Persona/Skill:** Amelia (`bmad-agent-dev`)
- **Prompt (Summary):** "Implement `POST /api/v1/tokens/check-allowance` to deny requests when quota is exhausted."
- **AI Output (Summary):** `HTTPException(status_code=403, detail="Forbidden")` on exhaustion.
- **Human Decision:** **MODIFY** (Decided by **Alexis Delgado**)
- **Technical Rationale:** An allowance check is a query whose negative answer is a business decision, not a transport error. AD-6 requires every denial to be explained.
- **Adopted Design:** HTTP 200 with `allowed=false`, `reason_code="DAILY_QUOTA_EXCEEDED"` (Annex technical task 2), `reason="Daily token quota exhausted; resets at 00:00 UTC"` (Annex BDD) and `resets_at` as an ISO-8601 instant.
- **Artifacts Changed:** `src/adapters/inbound/router.py`, `src/domain/services.py`, `tests/unit/test_story_8_3_hard_denial.py`.

---

### Entry D-06: Deterministic In-Memory SQLite Test Suite Architecture
- **Phase/Story:** Test Engineering & Scaffold Verification
- **Persona/Skill:** Murat (`bmad-tea`)
- **Prompt (Summary):** "Design test configuration for Pytest to validate Gherkin acceptance criteria."
- **AI Output (Summary):** In-memory SQLite with `StaticPool` and FastAPI `dependency_overrides[get_db]`.
- **Human Decision:** **ACCEPT** (Decided by **Valentina Gómez**)
- **Technical Rationale:** Fast, isolated tests with no external database server.
- **Post-review status:** The original claim of "zero residual disk side-effects" was false: the app lifespan ran `create_all` on the real `DATABASE_URL` and created `tuqs.db` in the working directory, and fixtures used the wall-clock date. Both fixed in **D-10**. An in-memory `StaticPool` database is a single connection, so it cannot test concurrency; that gap is covered by the file-backed test added in D-07.

---

### Entry D-07: Atomic In-Database Increment (supersedes D-02)
- **Phase/Story:** Story 8.1 — post-implementation adversarial review
- **Persona/Skill:** Claude Code (code review)
- **Evidence:** 8 threads posted 40 events of 100 tokens against a file-backed SQLite database. The ledger summed 4,001 tokens while `user_quotas.tokens_used` ended at 801: 80% of consumption lost.
- **Human Decision:** **REJECT & REWRITE** (Decided by **Alexis Delgado**)
- **Adopted Design:** `SQLQuotaRepository.record_consumption` runs in one transaction: `INSERT … ON CONFLICT DO NOTHING` provisions the daily row, `UPDATE user_quotas SET tokens_used = tokens_used + :n … RETURNING` increments in the database, the ledger row is appended, then a single commit. Any failure rolls back both. `OperationalError` is translated to `StorageUnavailableError` (HTTP 503 + `Retry-After: 5`, AD-7).
- **Verification:** `tests/integration/test_atomic_consumption.py`: 8 threads × 25 events → counter = ledger sum = 20,000 (AD-4 conservation); a failed ledger insert leaves the counter unchanged.
- **Artifacts Changed:** `src/adapters/outbound/sql_repository.py`, `src/ports/repository.py`, `src/application/use_cases.py`, `tests/integration/test_atomic_consumption.py`.

---

### Entry D-08: Contract-Bound API (OpenAPI 3.1 enforced by test)
- **Phase/Story:** All stories — review
- **Persona/Skill:** Claude Code (code review)
- **Evidence:** `docs/contracts/openapi.yaml` (copied from Solu-2) declared `/v1/quota/reserve`, `/v1/quota/settle` and `/v1/admin/allocations`, none of which exist, and omitted every endpoint Impl-1 exposes. This breaks the "Zero Hallucinated Endpoints" rule.
- **Human Decision:** **REJECT & REWRITE** (Decided by **Alexis Delgado**)
- **Adopted Design:** New `docs/contracts/openapi.yaml` v1.1.0 for the Impl-1 slice, including headers and error envelope. `tests/contract/test_openapi_contract.py` fails if operations, status codes, payload schemas, required fields or numeric/length bounds drift from the running app. The Solu-2 contract and its (P, Q, I) document are archived unchanged in `docs/contracts/solu2/` for Impl-2.
- **Artifacts Changed:** `docs/contracts/openapi.yaml`, `docs/contracts/solu2/*`, `tests/contract/test_openapi_contract.py`.

---

### Entry D-09: Uniform Error Envelope and Input Bounds
- **Phase/Story:** All stories — review
- **Persona/Skill:** Claude Code (code review)
- **Evidence:** 400 returned `{"detail": {...}}`, 422 returned `{error, code, details, path}`, 404 returned `{"detail": "Not Found"}`, and `prompt_tokens: 10**20` produced a plain-text `500 Internal Server Error` (integer overflow in the database).
- **Human Decision:** **MODIFY** (Decided by **Alexis Delgado**)
- **Adopted Design:** `src/adapters/inbound/errors.py` registers handlers for domain errors, validation errors, HTTP errors and unexpected exceptions; all return `ErrorBody {error_code, message, correlation_id, timestamp, details}` and echo `X-Correlation-ID`. Unexpected errors are logged with the correlation id and never leak internals. DTOs bound tokens to `≤ 1,000,000` and identifiers to 64 characters (the column width).
- **Verification:** `tests/unit/test_error_handling.py`, oversized and negative payload tests in the story suites.

---

### Entry D-10: Application Layer, Injectable Clock and Migrations
- **Phase/Story:** Scaffolding — review
- **Persona/Skill:** Claude Code (code review)
- **Evidence:** The router instantiated `SQLQuotaRepository`, `SystemClock` and the fleet adapter, imported SQLAlchemy and ran `text("SELECT 1")`. `IClock` existed but was never injected (AD-5); tests seeded with the real date and could fail when crossing 00:00 UTC. Tables were created with `create_all`; there were no migrations.
- **Human Decision:** **MODIFY** (Decided by **Alexis Delgado**)
- **Adopted Design:** Use cases in `src/application/use_cases.py` depend only on ports; `src/composition.py` is the single composition root and exposes FastAPI providers (`get_clock`, `get_repository`, …) that tests override with `FakeClock` (fixed at 2026-10-25T12:00:00Z). Alembic revision `0001` creates both tables with CHECK constraints; the lifespan runs `alembic upgrade head` when `AUTO_MIGRATE=true`, and the test suite disables it so no file is created.
- **Verification:** `tests/integration/test_migrations.py` (Alembic schema equals ORM metadata), `test_story_8_3_new_day_resets_allowance` (clock advanced past midnight).
- **Artifacts Changed:** `src/application/`, `src/composition.py`, `src/adapters/inbound/router.py`, `src/ports/clock.py`, `migrations/`, `alembic.ini`, `tests/conftest.py`, `tests/fixtures/fake_clock.py`.

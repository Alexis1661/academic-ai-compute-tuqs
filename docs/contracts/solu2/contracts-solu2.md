# Behavioral Contracts Specification — Module 8 (TUQS)

**System:** Academic AI Compute Management Platform  
**Module:** Module 8 — Token Usage and Quota Service (TUQS)  
**Lead Architect:** Alexis Delgado  
**Test Lead:** Valentina Gómez  
**Date:** October 19, 2026  
**Status:** APPROVED & BINDING  

---

## 1. Core Behavioral Contracts

This document establishes mathematically rigorous, machine-enforceable Design-by-Contract ($P$, $Q$, $I$) specifications for the three core operations of Module 8. In compliance with the Solu-2 specification standard, elastic adjectives (*appropriately, efficiently, gracefully, robustly, securely, properly*) are strictly prohibited; all guarantees are declared via concrete types, ranges, mathematical inequalities, status codes, and database invariants.

---

### Operation 1: `reserveTokens`

```python
async def reserve_tokens(
    request_id: str,
    subject_type: Literal["student", "group", "course"],
    subject_id: str,
    course_id: str,
    requested_tokens: int,
    idempotency_key: str,
    ttl_seconds: int = 300,
) -> ReservationDecisionDTO:
    ...
```

- **Hexagonal Layer:** Inbound Port (`IQuotaAdmissionUseCase`) &rarr; Core Domain Evaluator
- **Preconditions ($P$):**
  - **P1 (Input Format & Ranges):**
    - `request_id` MUST be a valid UUIDv4 string (regex `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`). Failure &rarr; `ERR_INVALID_REQUEST_ID`, HTTP 422.
    - `requested_tokens` MUST be an integer in the interval $[1, 32768]$. Failure &rarr; `ERR_TOKEN_RANGE_INVALID`, HTTP 422.
    - `ttl_seconds` MUST be an integer in the interval $[30, 3600]$. Failure &rarr; `ERR_TTL_OUT_OF_BOUNDS`, HTTP 422.
    - `idempotency_key` MUST be a non-empty string of length $\le 128$. Failure &rarr; `ERR_IDEMPOTENCY_KEY_INVALID`, HTTP 422.
  - **P2 (Identity & Enrollment Verification):**
    - `subject_id` MUST exist in the mock identity fixture. Failure &rarr; `ERR_ENTITY_NOT_FOUND`, HTTP 404.
    - `subject_id` MUST be currently enrolled in `course_id`. Failure &rarr; `QR_NOT_ENROLLED`, HTTP 403.
    - An active allocation record for `course_id` MUST exist in `allocation`. Failure &rarr; `QR_NO_ALLOCATION`, HTTP 403.
  - **P3 (Idempotency Hash Verification):**
    - If `idempotency_key` exists in `idempotency_record`, the stored SHA-256 payload checksum MUST match the current request checksum. Failure &rarr; `ERR_IDEMPOTENCY_MISMATCH`, HTTP 422.
- **Postconditions ($Q$):**
  - **Q1 (Return Value Schema):**
    - Returns `ReservationDecisionDTO` containing: `decision` (`ALLOW` | `DENY` | `CONSTRAIN`), `reservation_id` (UUIDv4 or null), `granted_tokens` (integer $\ge 0$), `failing_buckets` (list of strings), and `trace` (`DecisionTraceDTO`).
  - **Q2 (State Mutation on ALLOW):**
    - Evaluated when for all locked buckets $b \in \{B_{\text{student}}, B_{\text{group}}, B_{\text{course}}\}$:
      $$\text{available}(b) = \max(0, \text{limit}(b) - \text{consumed}(b) - \text{reserved}(b)) \ge \text{requested\_tokens}$$
    - Exactly one new row inserted into `reservation` with status `ACTIVE`, `reserved_tokens = requested_tokens`, and `expires_at = clock.now() + ttl_seconds`.
    - Exactly one row inserted into `reservation_bucket` per locked bucket linking `(reservation_id, bucket_id, requested_tokens)`.
    - In each locked bucket: `bucket.reserved = bucket.reserved + requested_tokens`.
    - Exactly one row inserted into `admission_decision` recording `decision = 'ALLOW'`.
  - **Q3 (State Mutation on CONSTRAIN):**
    - Evaluated when `allocation.on_insufficient == 'CLAMP'` and $\min_{b}(\text{available}(b)) > 0$ but $< \text{requested\_tokens}$.
    - Exactly one new row inserted into `reservation` with status `ACTIVE`, `reserved_tokens = min_available`, and `expires_at = clock.now() + ttl_seconds`.
    - In each locked bucket: `bucket.reserved = bucket.reserved + min_available`.
    - Exactly one row inserted into `admission_decision` recording `decision = 'CONSTRAIN'` and `rule_id = 'QR_CONSTRAIN_CLAMP'`.
  - **Q4 (State Mutation on DENY):**
    - Evaluated when $\min_{b}(\text{available}(b)) < \text{requested\_tokens}$ and policy is `DENY` (or `CLAMP` with 0 available).
    - Zero rows created in `reservation` or `reservation_bucket`.
    - Zero balance changes in `bucket.reserved` or `bucket.consumed`.
    - Exactly one row inserted into `admission_decision` recording `decision = 'DENY'`, citing the specific rule code from `RULE_CATALOG` (`QR_001` to `QR_004`), the failing bucket IDs, observed balance, and limit.
    - HTTP response code is 429 Too Many Requests (or 403 Forbidden for policy violations).
  - **Q5 (80% Soft Warning Outbox Trigger):**
    - If for any locked bucket $b$, $(\text{consumed}(b) + \text{reserved}(b)) / \text{limit}(b) \ge 0.80$ AND no warning row exists in `notification` for `(bucket_id, period_key)`, insert exactly one notification outbox row with `event_type = 'THRESHOLD_80_PERCENT'`.
  - **Q-fail (Failure Guarantee):**
    - On any precondition violation, database error, or connection timeout, the transaction issues a full `ROLLBACK`. Zero modifications persist in `bucket`, `reservation`, or `ledger`.
- **Invariants ($I$):**
  - **I1 (No Overdraw Invariant):** At all times and for all buckets:
    $$\text{consumed} + \text{reserved} \le \text{limit}$$
    *Bound to:* Invariant `AD-1`, Invariant `AD-3`, PostgreSQL CHECK constraint `chk_bucket_no_overdraw`.
  - **I2 (Deterministic Lock Order):** All bucket rows are acquired via `SELECT ... FOR UPDATE` in strict ascending canonical order:
    $$\text{rank}(\text{student}) < \text{rank}(\text{group}) < \text{rank}(\text{course})$$
    *Bound to:* Invariant `AD-1`, preventing all deadlocks.
- **Concurrency & Idempotency:**
  - Simultaneous requests contending on the same bucket are serialized by row-level locks. If two requests request 4,000 tokens with 500 remaining, exactly one is granted and the second is denied (`DENY`) or clamped to remainder (`CONSTRAIN`).
  - Repeated request with the same `idempotency_key` and identical payload returns the cached `ReservationDecisionDTO` without executing duplicate balance deductions.
- **Time Semantics:** System time accessed exclusively via `ClockPort.now()`. Period keys computed in timezone `'America/Bogota'` with half-open daily interval `[00:00:00, 24:00:00)`.
- **Latency Budget (NFR-1):** $p95 \le 50\text{ms}$, $p99 \le 120\text{ms}$ at 100 concurrent requests on 4 vCPU.

---

### Operation 2: `commitUsage`

```python
async def commit_usage(
    reservation_id: str,
    actual_tokens: int,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    idempotency_key: str,
) -> UsageSettlementDTO:
    ...
```

- **Hexagonal Layer:** Inbound Port (`IUsageSettlementUseCase`) &rarr; Core Domain Settlement Engine
- **Preconditions ($P$):**
  - **P1 (Input Format & Ranges):**
    - `reservation_id` MUST be a valid UUIDv4 string. Failure &rarr; `ERR_INVALID_RESERVATION_ID`, HTTP 422.
    - `actual_tokens` MUST equal `prompt_tokens + completion_tokens`. Failure &rarr; `ERR_TOKEN_SUM_MISMATCH`, HTTP 422.
    - `prompt_tokens` MUST be an integer $\ge 0$. Failure &rarr; `ERR_TOKEN_NEGATIVE`, HTTP 422.
    - `completion_tokens` MUST be an integer $\ge 0$. Failure &rarr; `ERR_TOKEN_NEGATIVE`, HTTP 422.
    - `model_id` MUST exist in `fixture_model_rate`. Failure &rarr; `ERR_MODEL_UNKNOWN`, HTTP 404.
  - **P2 (Reservation Existence & State):**
    - `reservation_id` MUST match an existing record in table `reservation`. Failure &rarr; `ERR_RESERVATION_NOT_FOUND`, HTTP 404.
- **Postconditions ($Q$):**
  - **Q1 (Normal Active Settlement):**
    - If `reservation.status == 'ACTIVE'`:
      - `reservation.status` transitions to `'SETTLED'`.
      - For each bound bucket in `reservation_bucket`:
        - `bucket.reserved = bucket.reserved - reservation_bucket.reserved_tokens`.
        - `bucket.consumed = bucket.consumed + actual_tokens`.
      - Exactly one row inserted into `usage_event` recording `reservation_id`, `actual_tokens`, `prompt_tokens`, `completion_tokens`, and calculated `gpu_seconds`.
      - Returns `UsageSettlementDTO(status='SETTLED', refunded_tokens=max(0, reserved_tokens - actual_tokens), gpu_seconds=...)`.
  - **Q2 (Late Settlement on Expired Reservation):**
    - If `reservation.status == 'EXPIRED'`:
      - `reservation.status` transitions to `'SETTLED_LATE'`.
      - `bucket.reserved` is NOT modified (was already refunded by the sweeper).
      - `bucket.consumed = bucket.consumed + actual_tokens`.
      - Overrun recorded: if `bucket.consumed > bucket.limit`, `overrun_tokens = bucket.consumed - bucket.limit`.
      - Exactly one row inserted into `audit_events` with `event_type = 'LATE_SETTLE_OVERRUN'`.
      - Returns `UsageSettlementDTO(status='SETTLED_LATE', overrun_tokens=overrun_tokens, ...)`.
  - **Q3 (Idempotent Replay):**
    - If `reservation.status IN ('SETTLED', 'SETTLED_LATE')`:
      - Returns the previously persisted `UsageSettlementDTO` with zero additional balance changes.
  - **Q4 (GPU-Second Compute Derivation):**
    - GPU-seconds calculated via formula:
      $$\text{gpu\_seconds} = \frac{\text{prompt\_tokens}}{\text{prefill\_tps}} + \frac{\text{completion\_tokens}}{\text{decode\_tps}}$$
  - **Q-fail (Failure Guarantee):**
    - If database write fails, transaction rolls back; reservation status and bucket counters remain untouched.
- **Invariants ($I$):**
  - **I3 (Ledger Balance Conservation):** For every bucket $b$, the current value of `bucket.consumed` MUST equal the sum of all confirmed ledger deltas in `usage_event_bucket`:
    $$\text{bucket.consumed} = \sum_{\text{event } \in E_b} \text{delta\_tokens}$$
    *Bound to:* Invariant `AD-4` (Single Source of Truth: Ledger).
- **Concurrency & Idempotency:** Executed within an atomic transaction with row locks on `reservation` and target `bucket` rows. Safe against concurrent settlement and sweeper expiration.
- **Latency Budget (NFR-1):** $p95 \le 30\text{ms}$ at 100 concurrent requests.

---

### Operation 3: `releaseExpiredReservations`

```python
async def release_expired_reservations(
    cutoff_time: datetime,
    batch_size: int = 100,
) -> SweeperSummaryDTO:
    ...
```

- **Hexagonal Layer:** Outbound Sweeper Worker &rarr; Persistence Adapter
- **Preconditions ($P$):**
  - **P1:** `cutoff_time` MUST be a timezone-aware UTC datetime. Failure &rarr; `ERR_TIMEZONE_NOT_UTC`.
  - **P2:** `batch_size` MUST be an integer in the interval $[1, 500]$. Failure &rarr; `ERR_BATCH_SIZE_INVALID`.
- **Postconditions ($Q$):**
  - **Q1 (State Transition):**
    - Selects up to `batch_size` reservations where `status = 'ACTIVE'` and `expires_at < cutoff_time` ordered by `id` FOR UPDATE SKIP LOCKED.
    - For each selected reservation, sets `status = 'EXPIRED'` and `updated_at = clock.now()`.
  - **Q2 (Atomic Balance Refund):**
    - For each selected reservation, locks corresponding buckets in canonical rank order (AD-1) and executes:
      `bucket.reserved = bucket.reserved - reservation_bucket.reserved_tokens`
  - **Q3 (Telemetry & Audit Emission):**
    - Emits metrics counter `tuqs_reservations_expired_total` incremented by the number of expired reservations.
    - Inserts audit row in `audit_events` for each batch sweep.
    - Returns `SweeperSummaryDTO(scanned_count=N, expired_count=M, refunded_tokens=R)`.
  - **Q-fail:** If an individual reservation lock fails, transaction aborts without corrupting other reservations.
- **Invariants ($I$):**
  - **I4 (Zero Zombie Holds):** No reservation in status `EXPIRED` shall retain a non-zero hold in `bucket.reserved`.
    *Bound to:* Invariant `AD-7` (Fail Closed & Expire Every Hold).
- **Concurrency & Idempotency:**
  - Uses `FOR UPDATE SKIP LOCKED` to allow multiple sweeper workers to run concurrently without deadlocks or duplicate work.
- **Latency Budget:** Execution of 100 expirations completes within $\le 500\text{ms}$.

---

## 2. Typed Error Catalog

The following catalog defines all error codes emitted across Module 8 APIs and domain ports:

| Error Code | HTTP Status | Trigger Condition | Human-Readable Explanation Template | Retryable |
|---|:---:|---|---|:---:|
| `QR_001` | 429 | Student daily quota exhausted. | `Student daily quota exceeded. Limit: {limit}, Consumed: {consumed}, Reserved: {reserved}. Resets at: {reset_at}.` | No |
| `QR_002` | 429 | Group daily quota exhausted. | `Project team quota exceeded for {group_id}. Available: {available}. Resets at: {reset_at}.` | No |
| `QR_003` | 429 | Course daily quota exhausted. | `Course daily budget for {course_id} exhausted. Contact instructor {instructor_email}.` | No |
| `QR_004` | 429 | Course monthly ceiling reached. | `Course monthly token ceiling exceeded. Allocations locked until next billing period.` | No |
| `QR_NOT_ENROLLED` | 403 | User not enrolled in course. | `User {user_id} is not enrolled in course {course_id}.` | No |
| `QR_NO_ALLOCATION` | 403 | Course has no token budget. | `No active token quota allocation configured for course {course_id}.` | No |
| `ERR_TOKEN_RANGE_INVALID` | 422 | Tokens outside $[1, 32768]$. | `Requested token count {requested} must be between 1 and 32,768.` | No |
| `ERR_IDEMPOTENCY_MISMATCH` | 422 | Key reused with different body. | `Idempotency key {key} was previously submitted with a different payload.` | No |
| `ERR_RESERVATION_NOT_FOUND` | 404 | Unknown reservation ID. | `Reservation {reservation_id} does not exist.` | No |
| `ERR_SERVICE_UNAVAILABLE` | 503 | Database pool or lock timeout. | `Token quota service temporarily saturated. Retry after {retry_after} seconds.` | Yes (5s) |

---

## 3. Invariant Binding Table

| Invariant Clause | Architectural Decision | Physical Enforcement Point | Test That Turns RED If Removed |
|---|:---:|---|---|
| **I1: No Overdraw** (`consumed + reserved <= limit`) | `AD-1`, `AD-3` | PostgreSQL DB constraint: `chk_bucket_no_overdraw CHECK (consumed + reserved <= daily_limit)` | `test_concurrent_reservations_cannot_exceed_limit` |
| **I2: Canonical Lock Order** (Student &rarr; Group &rarr; Course) | `AD-1` | Admission Service query generator: `ORDER BY subject_type_rank ASC` | `test_deadlock_freedom_under_reverse_contention` |
| **I3: Ledger Conservation** (`consumed == sum(deltas)`) | `AD-4` | DB trigger / Worker reconciliation job: `reconcile_bucket_balances()` | `test_ledger_reconciliation_detects_counter_drift` |
| **I4: Zero Zombie Holds** (Sweep expired holds) | `AD-7` | Background Sweeper Worker SQL CAS: `WHERE status = 'ACTIVE' AND expires_at < now()` | `test_sweeper_releases_stale_reservations` |
| **I5: Immutable History** (Period keys are static) | `AD-5` | Primary Key constraint: `PRIMARY KEY (subject_type, subject_id, resource, period_type, period_key)` | `test_midnight_reset_does_not_mutate_historical_rows` |
| **I6: Mandatory Explainability** (Every non-ALLOW has rule) | `AD-6` | Domain Policy Evaluator schema assert: `DecisionTraceDTO.rule_id NOT NULL` | `test_denial_response_contains_valid_catalog_rule_id` |
| **I7: Optimistic Mutation Concurrency** | `AD-8` | Admin Allocation SQL: `WHERE allocation_id = :id AND version = :version` | `test_concurrent_admin_allocation_edits_throw_409` |

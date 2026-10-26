# PRD — Token Usage and Quota Service (Module 8)

**Product:** Academic AI Compute Fabric — Module 8
**Module:** Token Usage and Quota Service (TUQS)
**Tier:** Foundation
**Status:** **DRAFT v0.3 — PRD corrections applied after adversarial review and human triage**
**Language:** English
**Sources:** Plan-2 Task Statement (Module 8 Annex); University AI Compute Management Platform Brief

---

## 1. Purpose and Product Vision

Inference compute is finite. The Token Usage and Quota Service (TUQS) provides the metering and quota-management layer for the Academic AI Compute Fabric.

TUQS records AI resource consumption and enforces configured usage limits for students, groups, and courses. The service measures token consumption, request counts, and estimated GPU-seconds and provides transparent quota decisions before additional consumption is authorized.

TUQS must answer three questions:

1. **Can this request consume additional quota?**

   * Return an explicit `ALLOW`, `CONSTRAIN`, or `DENY` decision.
   * Provide the reason for the decision.

2. **What has been consumed, by whom, and against which budget?**

   * Maintain an auditable usage ledger.
   * Provide query and reporting capabilities.

3. **Is a user, group, or course approaching a configured limit?**

   * Provide an advisory warning when usage reaches 80%.
   * Enforce a hard limit when the configured quota is exhausted.

The module is designed as a standalone planning and prototype component. External platform services are represented through local fixtures, simulated callers, or mock data where required.

---

# 2. Named Protagonists

| Persona                 | Role                                                             | Need from TUQS                                                                                                                      |
| ----------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Gabriel Restrepo**    | Academic Dean, financially accountable for institutional compute | Assign course budgets, review consumption by course and period, and obtain auditable usage reports.                                 |
| **Sam Ortega**          | Undergraduate student in CS-301                                  | See remaining quota, receive warnings before reaching the limit, and understand why a request was denied and when the quota resets. |
| **Prof. Lucía Herrera** | CS-301 instructor                                                | Monitor course consumption and adjust student or group sub-limits within the course allocation.                                     |
| **Tomás Vega**          | AI Lab Operations Engineer                                       | Inspect the usage ledger, verify resets, inspect quota events, and validate reconciliation behavior.                                |

Gabriel and Sam are the primary protagonists required by the module specification. Lucía and Tomás are supporting personas used for administration and operational scenarios.

---

# 3. Product Scope and Boundaries

## 3.1 TUQS owns

TUQS is responsible for:

* Ingestion and validation of token-consumption events.
* Maintenance of quota buckets for students, groups, and courses.
* Atomic reservation, settlement, release, and refund of quota.
* Evaluation of configured quota thresholds.
* Generation of structured quota breach reports.
* Course budget allocation.
* Daily and monthly quota periods.
* Automatic quota resets.
* Maintenance of the immutable usage ledger.
* Ledger query and export capabilities.
* Estimated GPU-seconds calculation based on configured model rates.
* Quota Management Console.
* Real-time Usage Ledger view.
* Simulated token traffic generator for the standalone prototype.

## 3.2 TUQS mocks or delegates

| Capability                             | Full-platform owner                             | TUQS behavior in standalone prototype                              |
| -------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------ |
| Identity, roles, and course enrollment | Module 1 — User, Role, Subject Access Manager   | Use local fixture data mapping user → group → course and role.     |
| Model catalog and VRAM information     | Module 5 — Model Catalog and Entitlement System | Use local model-rate fixtures.                                     |
| Inference routing                      | Module 7 — Local LLM Inference Gateway          | Use a simulated caller that invokes TUQS APIs.                     |
| GPU telemetry                          | Modules 3 and 11                                | Not consumed by TUQS. GPU-seconds are estimated from token counts. |
| Notification delivery                  | Platform                                        | Use an in-app notification feed and outbound event record.         |

## 3.3 Explicitly out of scope

The following capabilities are not part of TUQS:

* Authentication.
* API key issuance.
* Role management.
* Request-per-minute rate limiting.
* Model access or entitlement decisions.
* GPU scheduling.
* GPU reservation or placement.
* Monetary billing.
* Invoicing.
* Currency-based chargeback.
* Real tokenizer implementation.
* Multi-region deployment.
* Multi-institution deployment.
* Persistent high availability for V1.

TUQS manages **usage budgets**, not request-rate limits.

---

# 4. Assumptions

| ID  | Assumption                                                                                                                                              | Impact if incorrect                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| A-1 | The institutional time zone is America/Bogota (UTC−5, no DST).                                                                                          | Reset logic would require timezone/DST changes.                        |
| A-2 | Daily quota means the calendar day from 00:00:00 to 23:59:59 local time. Monthly quota means the calendar month. Unused daily quota does not roll over. | Rolling-window quota logic would be required instead.                  |
| A-3 | Quota token consumption equals `prompt_tokens + completion_tokens`.                                                                                     | Weighted token accounting would change quota calculations.             |
| A-4 | The caller supplies a unique `request_id` that remains stable across retries.                                                                           | Idempotency could not be guaranteed reliably.                          |
| A-5 | Streaming requests provide a maximum token value before execution. If omitted, TUQS applies the configured default reservation cap.                     | A request without `max_tokens` uses the defined default.               |
| A-6 | A request must explicitly provide one applicable course context for quota charging. TUQS never selects a course on the caller's behalf.                 | A different charging rule would be required for multi-course requests. |
| A-7 | Simulated callers are trusted to provide token counts.                                                                                                  | Metering fraud detection would be outside V1 scope.                    |
| A-8 | V1 operates as a standalone service with a single logical persistence layer.                                                                            | Distributed coordination requirements would increase.                  |

---

# 5. Domain Model

## 5.1 Bucket

A **bucket** represents a quota balance for a subject, resource, and period.

### Subject types

* `STUDENT`
* `GROUP`
* `COURSE`

### Resources

* `TOKENS` — mandatory.
* `REQUESTS` — supported when configured.
* `GPU_SECONDS` — supported when configured.

### Periods

* `DAILY`
* `MONTHLY`

## 5.2 Limit

A **limit** is the maximum amount of a configured resource that a bucket may consume during its period.

## 5.3 Consumed

**Consumed** is settled usage that has been permanently charged to a quota bucket.

## 5.4 Reserved

**Reserved** is quota temporarily held for an in-flight request.

## 5.5 Available

The available quota is:

`available = limit − consumed − reserved`

The system must never expose a negative available balance.

## 5.6 Admission hierarchy

A request is evaluated against every applicable quota bucket.

The deterministic evaluation order is:

1. Student daily.
2. Student monthly.
3. Group daily, when applicable.
4. Group monthly, when applicable.
5. Course daily.
6. Course monthly.

All applicable buckets are evaluated using one transaction snapshot.

The request is admitted only when the applicable quota policy allows every required bucket to support the reservation.

## 5.7 Reservation lifecycle

A reservation may transition through:

`RESERVED → SETTLED`

`RESERVED → RELEASED`

`RESERVED → EXPIRED`

Repeating `reserve` with the same `request_id` returns the existing reservation and never creates a second reservation.

## 5.8 Admission decisions

TUQS supports three decision types:

* `ALLOW` — the requested amount can be fully reserved.
* `CONSTRAIN` — the request is reduced to the remaining available amount when the configured policy permits clamping.
* `DENY` — the request cannot be admitted under the applicable quota policy.

Each bucket has:

`on_insufficient ∈ {DENY, CLAMP}`

If the policy is not explicitly configured, the value is `DENY`.

Only a `quota_admin` may change this policy.

---

# 6. Functional Requirements

Each functional requirement defines the system responsibility, trigger/input, expected behavior, and measurable verification condition.

---

## 6.1 Metering and Ledger

### FR-1 — Token Event Ingestion

**Scenario:** Token Metering Ingestion

TUQS shall record each valid consumption event exactly once and update every affected quota bucket.

**Input:**

`POST /v1/usage/events`

Required fields:

* `event_id`
* `request_id`
* `user_id`
* `course_id`
* `model_id`
* `prompt_tokens`
* `completion_tokens`
* `timestamp`

**Validation:**

* Token counts must be integers ≥ 0.
* `user_id` must exist in the configured fixture.
* `course_id` must exist in the configured fixture.
* `course_id` must correspond to a valid enrollment for the user.
* Timestamp must not be more than 24 hours in the past.
* Timestamp must not be more than 5 minutes in the future.
* `event_id` must be unique.

**Expected behavior:**

* Valid event → `201`.
* Duplicate event → `200` with the original result and no additional charge.
* Invalid event → `422` with field-level validation information.
* User not enrolled in the supplied course → `403 QR-NOT-ENROLLED`.

**Test criterion:**

When 1,000 events are submitted, including 50 duplicate events, the resulting ledger must contain only unique events and aggregate student and course usage must equal aggregate unique ledger usage.

---

### FR-2 — Atomic Multi-Bucket Update

TUQS shall update all affected student, group, and course buckets as one atomic operation.

Either all affected quota buckets reflect the event or none of them do.

**Test criterion:**

If a failure is injected after one bucket update but before the transaction completes, all affected bucket balances remain unchanged.

---

### FR-3 — GPU-Seconds Estimation

For settled requests, TUQS shall calculate estimated GPU-seconds using configured model rates.

Formula:

`gpu_seconds = prompt_tokens / prefill_rate + completion_tokens / decode_rate`

Configured rates must be greater than zero at fixture load. If a configured rate is zero or negative, prototype startup shall fail.

GPU time shall be stored as integer milliseconds, rounded half up.

Zero tokens produce `0 ms`.

**Test criterion:**

For a model with:

* prefill rate = 2,000 tokens/second
* decode rate = 50 tokens/second

a request containing:

* 1,000 prompt tokens
* 500 completion tokens

must produce:

`0.5 + 10 = 10.5 GPU-seconds`.

---

### FR-4 — Immutable Usage Ledger

The usage ledger shall be append-only.

Corrections shall be represented as new compensating records referencing the original event.

The service shall not expose update or delete operations for ledger records.

**Test criterion:**

Attempts to update or delete a ledger record through the service API must return an error, and application code must not perform update/delete operations against the ledger table.

---

### FR-5 — Ledger Query and Export

TUQS shall allow usage records to be filtered by:

* User.
* Group.
* Course.
* Model.
* Time range.

The ledger shall support pagination with a default page size of 100 records and CSV export.

**Test criterion:**

A 30-day query over 100,000 seeded ledger records shall return its first page within 500 ms at p95 under the reference test environment.

Token counters shall use 64-bit integers. No per-event token maximum is required in V1 because 64-bit counters prevent practical counter overflow within the prototype's operating envelope.

---

# 6.2 Admission, Reservation, and Enforcement

### FR-6 — Admission Check

**Scenarios:** Soft Warning and Hard Denial

TUQS shall evaluate whether a request can reserve additional quota.

**Input:**

`POST /v1/quota/reserve`

Required fields:

* `request_id`
* `user_id`
* `course_id`
* `model_id`
* `prompt_tokens_estimate`
* `max_tokens`

`course_id` is mandatory.

If `course_id` is absent, return `422`.

If the user is not enrolled in the supplied course according to the identity fixture, return:

`403 QR-NOT-ENROLLED`

The system never selects a course on the caller's behalf.

**Reservation amount:**

`required = prompt_tokens_estimate + max_tokens`

If `max_tokens` is omitted, `4,096` applies.

Values above `32,768` are rejected with `422`.

Each quota bucket has:

`on_insufficient ∈ {DENY, CLAMP}`

If the policy is unset, the value is `DENY`.

Only a `quota_admin` may change this policy through:

`PUT /v1/admin/buckets/{bucket_id}/policy`

**Expected result for an accepted request:**

* `ALLOW`
* `reservation_id`
* remaining balances
* `expires_at`

**Expected result under CLAMP:**

* `CONSTRAIN`
* `granted_tokens`
* `X-Quota-Constrained: true`
* structured quota report

**Expected result under DENY:**

* `DENY`
* structured Quota Breach Report
* zero quota consumption
* no successful reservation

**Test criterion:**

When available quota is 500 tokens and required quota is 4,000 tokens:

* Under `DENY`, zero reservations succeed.
* Under `CLAMP`, the request may receive at most 500 tokens.
* The test environment explicitly declares the policy under which it runs.

The V1 default policy is `DENY`.

---

### FR-7 — Atomic Reservation

Quota reservation shall be atomic.

A reservation shall succeed only if the applicable quota remains sufficient at the moment of the reservation operation.

If `max_tokens` is omitted, the service shall use the configurable default reservation cap of 4,096 tokens.

Reservation requests with `max_tokens > 32,768` shall be rejected with `422`.

Repeating `reserve` with the same `request_id` shall return the existing reservation and shall never create a second reservation.

**Mandatory concurrency behavior:**

For two simultaneous reservation attempts requiring 4,000 tokens against a bucket with only 500 available:

* Under `DENY`, zero reservations succeed.
* Under `CLAMP`, at most one reservation receives the remaining 500 tokens.
* Total reserved quota must never exceed 500.
* Available quota must never become negative.

**Scale verification:**

The test suite shall additionally execute:

* 1,000 concurrent `reserve` calls.
* Each request requires 4,000 tokens.
* All calls target one bucket with 500 available.
* The test is repeated 20 times.

Under `DENY`, zero requests succeed.

Under `CLAMP`, exactly one request receives 500 tokens and the remaining 999 requests are denied.

Across all runs:

`Σ reserved ≤ 500`

and:

`available ≥ 0`

---

### FR-8 — Settlement and Refund

When a request completes, the caller shall send:

`POST /v1/quota/settle`

with actual:

* `prompt_tokens`
* `completion_tokens`

TUQS shall convert the reservation into actual consumption and return unused reserved quota.

**Example:**

Reservation = 4,000 tokens

Actual usage = 1,200 tokens

Returned available quota:

`4,000 − 1,200 = 2,800`

**Overrun behavior**

If actual usage exceeds the reservation:

* Record the actual usage.
* Mark the ledger record as `OVERRUN`.
* Track the overrun amount separately.
* Prevent subsequent reservations for the affected subject until the configured recovery condition is met.
* Never display a negative available quota.

`BR-2` applies only when the reserve decision is `DENY`.

An admitted reservation whose actual usage exceeds its reserved amount follows the `OVERRUN` path.

Exactly one settlement is accepted per `reservation_id`.

`event_id` is unique at the database level.

**Test criterion:**

A 4,000-token reservation settled at 1,200 tokens must return 2,800 tokens.

A 1,000-token reservation settled at 1,300 tokens must create an `OVERRUN` record containing the 300-token difference.

---

### FR-9 — Reservation Expiry

A reservation that is not settled or released before its configured TTL shall automatically transition to `EXPIRED`.

Default TTL:

`300 seconds`

Allowed configuration range:

`30–3,600 seconds`

Repeating `reserve` with the same `request_id` returns the existing reservation and never creates a second one.

A `settle` received after reservation expiry shall be recorded as `LATE_SETTLE` against the original quota period and shall not restore the released reservation.

**Test criterion:**

With a configured TTL of 5 seconds, an unsettled reservation must be released within 10 seconds and the previously reserved quota must become available again.

---

### FR-10 — Structured Quota Breach Report

Every `DENY` and `CONSTRAIN` response shall provide both machine-readable and human-readable explanations.

The report shall contain:

* `decision`
* `rule_id`
* `bucket`
* `subject`
* `resource`
* `period`
* `limit`
* `consumed`
* `reserved`
* `requested`
* `available`
* `reset_at`
* `suggested_action`
* `explanation`

`reset_at` shall use ISO-8601 format and represent the institutional America/Bogota timezone.

**Test criterion:**

Every `DENY` generated during the test suite must contain all required fields, and its `rule_id` must reference a defined quota rule.

---

### FR-11 — Soft Warning at 80%

When the combined `consumed + reserved` usage of a quota bucket crosses 80% of its limit for the first time during a period, TUQS shall:

1. Add an `X-Quota-Warning: 80` response header.
2. Add `X-Quota-Remaining`.
3. Create one in-app notification for the affected student.
4. Prevent duplicate 80% notifications for the same bucket and period.

**Crossing definition:**

Crossing means:

`(consumed + reserved) / limit` moves from `< 0.80` to `≥ 0.80`.

The notification is created once per bucket per period.

The flag `warning_80_emitted_at` is never cleared during that period, even if a refund lowers usage below 80%.

The response header `X-Quota-Warning: 80` is returned on every response while usage is `≥ 80%`.

If usage later falls below 80% and crosses the threshold again, no additional notification is generated for the same bucket and quota period.

**Test criterion:**

For a 100,000-token daily limit, if usage changes from 79,000 to 80,500 tokens, the warning must be generated exactly once.

---

### FR-12 — Hard Denial at 100%

When a bucket has no sufficient available quota under its configured policy, new reservations shall be denied until:

* the quota period resets, or
* an authorized limit adjustment provides additional quota.

**Test criterion:**

A student at 100,000/100,000 daily tokens attempting another request must receive:

`DENY`

with a quota-exceeded response and:

`rule_id = QR-HARD-100`

---

### FR-13 — Bucket Hierarchy Enforcement

TUQS shall evaluate every applicable quota bucket.

A request shall not be admitted solely because the student has remaining quota if a required parent course quota is exhausted.

All applicable buckets shall be read from one transaction snapshot.

**Evaluation order:**

1. Student daily.
2. Student monthly.
3. Group daily, when applicable.
4. Group monthly, when applicable.
5. Course daily.
6. Course monthly.

All applicable buckets must be evaluated before admission.

The **binding bucket** is the first applicable bucket in the deterministic evaluation order for which:

`available < required`

The report shall also include:

`all_failing_buckets`

containing every applicable bucket that cannot support the requested reservation.

**Test criterion:**

If:

* student daily available = 50,000 tokens
* course daily available = 0 tokens

the request must be denied and the report must identify:

`COURSE / TOKENS / DAILY`

as the binding bucket.

---

# 6.3 Budget Administration

### FR-14 — Course Budget Allocation

**Scenario:** Course Budget Allocation and Reset

An authorized administrator shall create or update a course allocation for a defined period.

The service shall reject sub-allocations whose total exceeds the course allocation.

**Test criterion:**

If CS-301 has a 5,000,000-token allocation, attempting to create sub-allocations totaling 5,100,000 tokens must be rejected with `422`.

---

### FR-15 — Automatic Reset

TUQS shall reset daily quotas at:

`00:00:00 America/Bogota`

and monthly quotas at the beginning of each calendar month.

Unused daily quota expires at the end of the calendar day and is never carried forward.

The monthly limit caps total consumption regardless of daily distribution.

Reset behavior shall be idempotent.

A reset operation executed twice for the same period must not produce duplicate effects.

A reservation stores the `period_key` of every affected bucket at creation time.

For example:

`2026-09-27`

Settlement writes to those original period buckets even after rollover.

The new period's bucket is unaffected by settlement of the previous period's reservation.

The quota period charged for a reservation is determined at reservation creation time. Settlement after a quota-period boundary does not move the reservation to the new period.

The excess consumption possible across a boundary is bounded by one reservation per in-flight request. This is an accepted trade-off for V1.

**Test criterion:**

When a simulated clock crosses midnight:

* Daily consumed values become 0 within 5 seconds.
* Repeating the same reset produces no additional changes.
* A reservation created at 23:59:58 and settled at 00:00:03 remains charged to the previous quota period.

---

### FR-16 — Limit Adjustment with Audit

Authorized roles shall be able to increase or decrease configured quota limits.

Every adjustment shall record:

* Actor.
* Timestamp.
* Previous value.
* New value.
* Reason.

If a limit is reduced below current consumption, the bucket shall remain recorded with its actual consumption and new requests shall be denied until the quota becomes available again or the limit is adjusted.

**Test criterion:**

Every limit adjustment produces exactly one corresponding audit record.

---

### FR-17 — Usage Reporting

TUQS shall generate period-based course reports containing:

* Total tokens.
* Prompt tokens.
* Completion tokens.
* Request count.
* Estimated GPU-seconds.
* Top 10 consumers.
* Percentage of course allocation consumed.

A reconciliation job shall assert, for every `(bucket, period_key)`:

`consumed = Σ settled ledger tokens`

The reconciliation includes compensating records and `OVERRUN` rows according to their signed ledger effect.

Report totals and ledger queries shall use the same shared query function.

**Test criterion:**

Report totals must equal the corresponding ledger totals for the same filter and period.

Discrepancy must equal zero after every test run and at least every 60 seconds in the prototype.

---

# 6.4 Prototype Surfaces

### FR-18 — Quota Management Console

The prototype shall provide a web console that allows authorized administrators to:

* View quota allocations.
* View bucket status.
* View warnings.
* View denials.
* Manage configured allocations and limits.

The exact page structure and interaction design will be specified during the UX phase.

---

### FR-19 — Real-Time Usage Ledger

The prototype shall provide a usage ledger view with:

* Live usage events.
* User filtering.
* Group filtering.
* Course filtering.
* Model filtering.
* Time filtering.

New ingestion events shall appear in the view within 2 seconds.

The exact interaction design will be specified during the UX phase.

---

### FR-20 — Simulated Token Traffic Generator

The standalone prototype shall include a mechanism for generating simulated usage traffic.

The generator shall support configuration of:

* Users.
* Request rate.
* Prompt-token distribution.
* Completion-token distribution.
* Duplicate events.
* Streaming behavior.
* Concurrency race scenario.

A predefined concurrency test must allow deterministic validation of FR-7.

---

# 7. Non-Functional Requirements

| ID     | Category             | Requirement                                                                                                                                                                    | Verification                                              |
| ------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| NFR-1  | Performance          | Admission decision p95 ≤ 50 ms and p99 ≤ 120 ms at 100 concurrent requests under the reference environment.                                                                    | Load test.                                                |
| NFR-2  | Throughput           | Sustain ≥ 500 usage events/s for 60 seconds with zero lost events.                                                                                                             | Load test.                                                |
| NFR-3  | Correctness          | Across 1,000 concurrent reservation attempts against one bucket, granted reservations must never exceed available quota and negative balances must equal zero.                 | Concurrency test, 20 repetitions.                         |
| NFR-4  | Idempotency          | Duplicate `event_id` or `request_id` submissions, including up to 10 retries, must change quota balances by exactly zero after the first successful operation.                 | Property test.                                            |
| NFR-5  | Consistency          | For every `(bucket, period_key)`, settled usage must equal the corresponding settled ledger usage, including compensating and `OVERRUN` rows according to their signed effect. | Reconciliation test every 60 seconds and after test runs. |
| NFR-6  | Reset Accuracy       | Daily and monthly resets must complete within 5 seconds of the configured reset time.                                                                                          | Simulated-clock test.                                     |
| NFR-7  | Notification Latency | The 80% notification must be created within 2 seconds of the threshold-crossing request.                                                                                       | Timestamp comparison.                                     |
| NFR-8  | Explainability       | 100% of DENY and CONSTRAIN responses must contain all FR-10 fields and a resolvable `rule_id`.                                                                                 | Automated schema validation.                              |
| NFR-9  | Security             | No bearer token, API key, or role claim may appear in application logs at any level. Quota administration endpoints require the configured administrative role.                | Log scan and authorization tests.                         |
| NFR-10 | Auditability         | 100% of limit changes and resets must produce an audit record containing actor and timestamp.                                                                                  | Audit coverage test.                                      |
| NFR-11 | Recovery             | After a process interruption during a reservation, quota balances must recover without negative available values and expired reservations must be released within 60 seconds.  | Crash-recovery test.                                      |
| NFR-12 | Portability          | The standalone prototype must be startable through the documented local deployment procedure on a clean machine without requiring GPU hardware.                                | Clean-run test.                                           |
| NFR-13 | Accessibility        | The quota console must target WCAG 2.1 AA requirements, including keyboard navigation, adequate contrast, and status information not conveyed by color alone.                  | Automated accessibility scan plus manual keyboard test.   |
| NFR-14 | Scalability Envelope | The service must correctly operate with seeded data representing 5,000 users, 60 courses, and 1,000,000 ledger rows.                                                           | Seeded-data test.                                         |
| NFR-15 | Time Handling        | Timestamps must be stored in UTC and displayed reset times must use America/Bogota.                                                                                            | Boundary and timezone tests.                              |

---

# 8. Scenario-to-Requirement Traceability

| Scenario                                         | Protagonist                         | Primary Functional Requirements | Key NFRs            |
| ------------------------------------------------ | ----------------------------------- | ------------------------------- | ------------------- |
| 1. Token Metering Ingestion                      | Tomás / simulated traffic generator | FR-1, FR-2, FR-3, FR-4, FR-20   | NFR-2, NFR-4, NFR-5 |
| 2. Soft Warning at 80%                           | Sam                                 | FR-6, FR-11                     | NFR-1, NFR-7        |
| 3. Hard Denial at 100%                           | Sam                                 | FR-6, FR-10, FR-12, FR-13       | NFR-8               |
| 4. Course Budget Allocation and Reset            | Gabriel                             | FR-14, FR-15, FR-16, FR-17      | NFR-6, NFR-10       |
| Mandatory Edge Case: Concurrent Reservation Race | Sam / two simulated requests        | FR-7, FR-8, FR-9, FR-20         | NFR-3, NFR-11       |

---

# 9. Failure and Non-Happy Paths

| Failure                                | Expected Behavior                                                                                                                                                      |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Student, group, or course quota breach | Request is denied with a structured FR-10 report and no partial quota charge.                                                                                          |
| Concurrent reservation race            | Reservation operation is atomic. A losing request receives an explained denial and available quota never becomes negative.                                             |
| Worker crash during streaming request  | Reservation eventually expires if no settlement occurs. Any valid previously reported usage is handled according to the settlement rules.                              |
| Duplicate or replayed usage event      | Event is processed idempotently and the original result is returned.                                                                                                   |
| Settlement exceeds reservation         | `OVERRUN` is recorded and additional reservations follow the configured overrun protection rule.                                                                       |
| Reset executes more than once          | Reset is idempotent for the same period.                                                                                                                               |
| Reset is delayed                       | Service performs the required catch-up behavior without deleting ledger history.                                                                                       |
| Database write failure                 | Reservation fails closed; no quota is consumed without a recorded reservation.                                                                                         |
| Unknown user or course                 | Unknown entity returns an entity-not-found response. For a supplied course that exists but is not associated with the user, the service returns `403 QR-NOT-ENROLLED`. |

---

# 10. Business Rules

**BR-1:** Every applicable quota bucket must be evaluated before a request is admitted.

**BR-2:** A request denied during the admission/reservation stage consumes zero quota and creates no successful reservation. An admitted request whose actual usage exceeds its reservation follows the `OVERRUN` path and is not treated as a denied request.

**BR-3:** Quota thresholds are evaluated using `consumed + reserved`.

**BR-4:** The 80% warning is generated once per bucket per quota period. The warning flag is never cleared during that period.

**BR-5:** Student and group sub-allocations cannot exceed the parent course allocation.

**BR-6:** Reset operations never delete historical ledger records.

**BR-7:** Only authorized quota-administration roles can change course-level limits.

**BR-8:** Instructors may only adjust student or group sub-limits within courses for which they have the corresponding administrative authority.

**BR-9:** Unused daily quota does not roll over into the next calendar day.

**BR-10:** No applicable bucket has an implicit unlimited quota. A request without an applicable configured allocation is denied with `QR-NO-ALLOCATION`.

---

# 11. Risks

| ID  | Risk                                                                                     | Mitigation                                                                                                   |
| --- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| R-1 | Reserving maximum tokens before execution can temporarily make quota appear unavailable. | Use reservation TTL, settlement refund, and separate display of reserved versus consumed quota.              |
| R-2 | Callers may omit `max_tokens`.                                                           | Apply the configurable default reservation cap of 4,096 tokens and reject values above 32,768.               |
| R-3 | Reset behavior may be affected by timezone boundaries.                                   | Store timestamps in UTC, use the configured institutional timezone for resets, and test boundary conditions. |
| R-4 | Reported token counts may exceed reserved amounts.                                       | Record `OVERRUN`, reconcile usage, and apply the defined protection rule.                                    |
| R-5 | A reservation may remain open across a quota-period boundary.                            | Store the original `period_key` on reservation creation and settle against the original period.              |
| R-6 | Missing quota allocation could otherwise result in implicit unlimited access.            | Fail closed with `QR-NO-ALLOCATION`.                                                                         |

---

# 12. Open Questions and Deferred Decisions

The following decisions are intentionally deferred to the appropriate subsequent planning phase and must be tracked in the AI Decision Log and/or Architecture documentation.

| ID   | Question                                                                                  | Current Draft Position                                                                                                                                                     | Status                                                  |
| ---- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| OQ-1 | When a request exceeds remaining quota, should the default behavior be `DENY` or `CLAMP`? | V1 default is `DENY`. `CLAMP` may be enabled only through explicit policy configuration.                                                                                   | **Resolved**                                            |
| OQ-2 | Should `REQUESTS` and `GPU_SECONDS` be enforced in V1 or only metered?                    | `REQUESTS` and `GPU_SECONDS` are metered when supported. Enforcement occurs only when a corresponding limit is explicitly configured.                                      | **Resolved**                                            |
| OQ-3 | If a user has multiple course contexts, how is the charging course selected?              | V1 requires the caller to supply exactly one course context per request. TUQS never selects a course on the caller's behalf. Multi-course charging is outside V1.          | **Resolved for V1; multi-course behavior out of scope** |
| OQ-4 | Does unused daily quota roll over?                                                        | No. V1 daily quotas do not roll over. Unused daily quota expires at the end of the calendar day.                                                                           | **Resolved**                                            |
| OQ-5 | Is a 300-second default reservation TTL sufficient for long-running streams?              | V1 uses a configurable 300-second default with a permitted range of 30–3,600 seconds. Long-running stream requirements remain deferred to architecture/operational review. | **Deferred**                                            |

No open question may silently change the requirements. Any accepted change must be recorded in the appropriate decision log and reflected in the affected requirements and tests.

---

# 13. Definition of Done for the PRD

The PRD is considered ready for adversarial review when:

* All four module scenarios are explicitly represented.
* The mandatory concurrency edge case is represented.
* Every scenario traces to at least one functional requirement.
* Every scenario traces to at least one measurable non-functional requirement.
* Functional requirements have explicit test criteria.
* Non-functional requirements have measurable verification criteria.
* Named protagonists are defined.
* Module boundaries and non-goals are explicit.
* Failure states are defined.
* Quota terminology is defined.
* No requirement depends on an unspecified external service without a mock or fixture.
* Open questions are explicitly marked as resolved or deferred.
* The PRD does not prescribe unnecessary implementation details that belong exclusively to the architecture phase.
* Daily quotas apply to the calendar day from 00:00:00 to 23:59:59 in America/Bogota.
* Unused daily quota does not roll over to the following period.
* The default insufficient-quota policy is `DENY`.
* `CLAMP` is only available through explicit quota policy configuration.
* Reservation size has a default of 4,096 tokens and a hard ceiling of 32,768 tokens.
* Reservation concurrency is tested at 1,000 simultaneous attempts.
* Reservation period ownership is preserved across quota-period boundaries.
* Ledger/report reconciliation is explicitly testable.
* Quota initialization fails closed when no allocation exists.
* Administrative roles and their boundaries are explicitly defined.

The PRD is then submitted to:

`/bmad-review --lens adversarial`

All findings must be triaged by the human team and recorded in:

`reviews/review-prd-adversarial.md`

---

# 14. Glossary

**Bucket** — A quota balance for a resource, subject, and period.

**Reservation** — A temporary hold on available quota for an in-flight request.

**Settlement** — Conversion of a reservation into actual consumed usage.

**Consumed** — Usage that has been finalized and charged to a quota bucket.

**Reserved** — Quota temporarily held for an active request.

**Available** — Remaining quota after subtracting consumed and reserved amounts.

**Binding bucket** — The first applicable quota bucket in the deterministic evaluation order that prevents a request from being fully admitted.

**Quota period** — The time interval over which a quota limit applies.

**Soft warning** — An advisory notification generated when usage crosses the configured 80% threshold for the first time during a quota period.

**Hard denial** — A rejection that occurs when the applicable quota cannot support the requested consumption under the configured policy.

**CLAMP** — A policy that reduces an admitted request to the amount of quota currently available.

**OVERRUN** — A settlement in which actual usage exceeds the amount originally reserved.

**LATE_SETTLE** — A settlement received after a reservation has expired; it is recorded against the original quota period and does not restore the released reservation.

**quota_admin** — The administrative role authorized to manage quota policies, course allocations, and quota limits.

**course_instructor** — A role authorized to adjust student or group sub-limits within courses where the role has administrative authority.

**student** — A read-only role authorized to inspect the student's own quota information.

**QR-NOT-ENROLLED** — Error code returned when a supplied course exists but the user is not enrolled in that course.

**QR-NO-ALLOCATION** — Error code returned when no applicable configured quota allocation exists.

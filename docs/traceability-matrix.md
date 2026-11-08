# Impl-2 traceability and quality gate

**Verdict: FAIL** (2026-11-08): measured k6 read p95 exceeds 50 ms; historical ATDD evidence remains unavailable. `PARTIAL` means relevant code or test exists, not that the complete PRD requirement passed. Test paths below are relative to `tests/`. Python execution: [test-evidence-impl2-final.txt](test-evidence-impl2-final.txt), 93 passed; browser: [3 passed](test-evidence-playwright-impl2-final.txt). No CI run was established in this review.

| PRD | Requirement | Story | Evidence | Verdict |
|---|---|---|---|---|
| FR-1 | Event ingestion | 8.1 | unit/test_story_8_1_ledger_ingestion.py | PARTIAL |
| FR-2 | Multi-bucket update | — | — | GAP |
| FR-3 | GPU-seconds estimation | — | — | GAP |
| FR-4 | Immutable ledger | 8.1 | integration/test_atomic_consumption.py | PARTIAL |
| FR-5 | Ledger query/export | — | — | GAP |
| FR-6 | Admission check | 8.3 | unit/test_story_8_3_hard_denial.py | PARTIAL |
| FR-7 | Atomic reservation | 8.4 | integration/test_story_8_4_atomic_reservation.py | PARTIAL |
| FR-8 | Settlement/refund | — | — | GAP |
| FR-9 | Reservation expiry | — | — | GAP |
| FR-10 | Quota breach report | 8.3 | unit/test_story_8_3_hard_denial.py | PARTIAL |
| FR-11 | Soft warning | 8.2 | unit/test_story_8_2_soft_warning.py | PARTIAL |
| FR-12 | Hard denial | 8.3 | unit/test_story_8_3_hard_denial.py | PARTIAL |
| FR-13 | Bucket hierarchy | — | — | GAP |
| FR-14 | Course allocation | — | — | GAP |
| FR-15 | Automatic reset | 8.5 | unit/test_story_8_5_midnight_reset.py; nfr/quota-batch-reset.js | PARTIAL |
| FR-16 | Limit adjustment/audit | — | — | GAP |
| FR-17 | Usage reporting | — | — | GAP |
| FR-18 | Management console | — | — | GAP |
| FR-19 | Real-time ledger | 8.6 | e2e/quota-breach-alert.spec.ts | PARTIAL |
| FR-20 | Traffic generator | — | — | GAP |

## Architectural decisions

The authoritative Solu-2 architecture defines AD-1 through AD-8; it does not define AD-9 through AD-18 in the inspected architecture. No meaning is invented for missing identifiers. The dossier specifies AD-19 for atomic quota reservation.

| Invariant | Evidence and scope | Verdict |
|---|---|---|
| AD-1 ordered multi-bucket transactions | 8.4 conditional reservation and independent SQLite connections, 20 races; no PostgreSQL or multi-bucket proof | PARTIAL |
| AD-2 idempotent writes | Explicitly deferred in sprint tracker | GAP |
| AD-3 bounded grants | 8.3 allowance and 8.4 reserve tests; ingestion may exceed limit | PARTIAL |
| AD-4 append-only ledger/reconciliation | 8.1 and integration/test_atomic_consumption.py; rollover preserves historical rows and ledger; full reconciliation not proven | PARTIAL |
| AD-5 period keys/clock/reset | injected clock and rollover tests create current-period rows without erasing history; external scheduler required | PARTIAL |
| AD-6 explainability | 8.3 denial tests; full rule catalog not proven | PARTIAL |
| AD-7 fail closed/expire holds | error handling tests; expiry deferred | PARTIAL |
| AD-8 authorized audited administration | shared admin secret enforced on reset and seed; individual roles and audit absent | GAP |
| AD-9–AD-18 | No corresponding definition found in inspected architecture | UNDEFINED |
| AD-19 atomic reservation | 8.4 barrier integration test passes 20 times on independent SQLite connections; PostgreSQL and 1,000-attempt stress unverified | PARTIAL |

## NFR and release evidence

NFR-1–15 appear in `prd.md`. No complete performance, throughput, idempotency, recovery, security, audit, accessibility or scale evidence was found. The k6 gate measured 2,000 period rollovers with 50 concurrent readers: read p95 661.55 ms (one worker) and 428.75 ms (four workers), both above 50 ms; reset completed within 2 seconds and all 2,000 physical current rows were zero. The reservation test uses independent SQLite connections but does not establish PostgreSQL locking or the PRD's 1,000 attempts. See [walkthrough](walkthrough-impl2.md) for browser and historical ATDD evidence.

## Performance follow-up, 2026-11-08

The unchanged k6 gate failed again after optimization. Four-worker repeats on the shared host yielded p95 990.12 ms and 463.11 ms; both had zero read errors and passed the 2,000-row physical audit. [Full investigation](evidence/performance-investigation.md). The release verdict remains **FAIL**.

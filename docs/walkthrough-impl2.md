# Impl-2 walkthrough — Module 8 TUQS

**Review:** 2026-11-08  
**Performance follow-up:** [investigation and latest runs](evidence/performance-investigation.md)  
**Overall verdict: FAIL** — the 50 ms read-latency threshold did not pass. Authentic historical red-phase evidence and documented human overrides are unavailable. See [traceability matrix](traceability-matrix.md).

## Changes and architecture

Story 8.4 uses a conditional database update for reservation. Its integration test now uses independently checked-out connections to a migrated, file-backed SQLite database. It repeats the 500-available / two concurrent 400-token requests 20 times and asserts a single 200, a 429, and 100 remaining, with persisted state. SQLite serializes writes; this is not evidence of PostgreSQL row locking or the PRD's 1,000-attempt stress criterion. Direct ingestion records actual usage and can exceed a limit; reservation grants remain bounded.

Story 8.5 now rolls forward to a new UTC-period row using the latest prior limit in one idempotent transaction. It preserves previous counters, ledger entries, and current-period consumption, rather than erasing a day's ledger-associated counter. The benchmark seeds 2,000 previous-day buckets above 80%, then confirms 2,000 new current-day buckets at zero. This interprets reset as period rollover, a deliberate correction to the original current-row mutation. An external scheduler must invoke the endpoint at midnight; an autonomous daemon is not supplied. A configured shared `ADMIN_TOKEN` is required for reset and test seed; the latter is additionally disabled by default and restricted to development/test. This is not role-based access control or actor-level auditing.

Story 8.6 uses a dashboard, page object and auto-retrying CSS assertions. Initial counters are consistently formatted and a refresh starts immediately. Playwright starts an isolated SQLite-backed server automatically, unless `BASE_URL` is explicitly supplied. A 95,000 + 6,000 actual-consumption overrun renders the depleted state; it is not a bounded reservation.

## Execution evidence

- Python: `python -m pytest --cov=src.domain --cov-branch --cov-report=term-missing -q`: **93 passed**, 98% combined domain coverage, 11/12 branches. [Full output](test-evidence-impl2-final.txt).
- Playwright: `npx playwright test` with the self-starting server: **3 passed**. [Full output](test-evidence-playwright-impl2-final.txt). Two authentic retry traces from an earlier failing run are retained under `docs/evidence/`; view with `npx playwright show-trace <trace.zip>`. First CSS-transition failures were fixed with auto-retrying assertions. The subsequent self-hosted run exposed initial formatting instability, also corrected; its [log](test-evidence-playwright-selfhosted-before.txt) is retained.
- ATDD: repository history shows the Story 8.4 test and implementation first appearing in the same commit `335466a`; no earlier red-phase transcript was found. A retrospective test failure would not establish the required chronology.
- Human testing overrides: the two proposed corrections in the decision log are recommendations, not evidenced historical human actions.

## k6: 2,000 buckets and 50 concurrent readers

Windows local host, Python 3.12, Uvicorn, isolated SQLite database; 50 sustained VUs for five seconds and reset started at one second. The script aborts on incorrect seed counts, requires 2,000 created buckets, checks all 2,000 HTTP balances and verifies no read errors; an independent physical SQLite query also verifies all rows. Threshold result below is genuine and **FAIL**. Read latency is not the PRD admission-decision latency measurement.

| Metric | Target | One worker | Four workers |
|---|---:|---:|---:|
| Reset | < 2,000 ms | 679 ms | 645 ms |
| Read latency p95 | < 50 ms | 661.55 ms | 428.75 ms |
| Read latency p99 | report | not captured | 608.48 ms |
| Read errors | 0% | 0% / 627 reads | 0% / 1,378 reads |
| Current rows at zero | 2,000 | 2,000 | 2,000 |
| Prior rows at 85,000 | 2,000 preserved | 2,000 | 2,000 |

Both k6 executions exited nonzero on the p95 threshold. See [run conditions and reproduction](evidence/k6-conditions.md), corresponding console logs, summary JSON and database audits. These are local results, not production or CI certification.

## Performance follow-up

Optimized dependency dispatch, session preparation, and the balance SELECT. The functional suite passed again (93 Python and 3 browser tests). In a controlled four-worker comparison, a baseline p95 of 159.86 ms and an intermediate p95 of 94.15 ms both exceeded the 50 ms target. Repeats of the final code yielded 990.12 and 463.11 ms on the shared machine; the substantial variability prevents a reliable improvement claim. All runs kept zero read errors and passed the physical-row audit. The overall gate remains **FAIL**. Full results and conditions: [performance investigation](evidence/performance-investigation.md).

## Outstanding release work

Reduce or renegotiate the measured latency target with a representative deployment and rerun the unmodified gate. Implement or provision a midnight scheduler and verify it. Establish role-based authorization and actor audit if required by the full PRD. The original ATDD chronology and human corrections require contemporaneous records; they cannot be fabricated retrospectively. The PRD also contains features and NFRs beyond this six-story slice.

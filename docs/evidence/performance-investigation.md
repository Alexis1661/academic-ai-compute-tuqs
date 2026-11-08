# Read latency investigation — 2026-11-08

**Outcome: FAIL** for the sustained 50-reader p95 target of < 50 ms. The work reduced unnecessary thread-pool dispatch in FastAPI's dependency graph, constructs the lazy SQLAlchemy session without a worker hop, closes it in a worker, and selects only the two fields needed for balance reads. Blocking database operations remain in worker threads; no quota cache or weakened test threshold was introduced.

## Conditions

Windows, Ryzen 5 7520U (4 cores/8 logical), Python 3.12.6, k6 2.3.0, fresh isolated file-backed SQLite with alembic migrations, 50 constant readers for five seconds, reset at t=1 s, 2,000 prior-period buckets and an audit of all physical rows. Uvicorn, k6 and other desktop applications share the host. Except where noted, four Uvicorn processes with access logging disabled were used. Every run had zero failed reads, exactly 2,000 returned reset buckets and a successful independent database audit. Each k6 exit was 99 because read p95 exceeded the unchanged 50 ms threshold. Read latency is not the separate NFR-1 admission latency.

## Results

| Run | Change | Workers | p95 ms | p99 ms | Reset ms | Reads |
|---|---|---:|---:|---:|---:|---:|
| baseline-comparable | Original dependency providers in isolated source copy | 4 | 159.86 | 203.90 | 272 | 2,150 |
| async-dependencies | Trivial providers async | 4 | 94.15 | 162.23 | 313 | 3,509 |
| lean-session-columns | Adds lazy session preparation and two-column SELECT | 4 | 95.91 | 142.77 | 255 | 4,200 |
| lean-wal | Same code, experimental SQLite WAL | 4 | 102.75 | 173.08 | 285 | 3,816 |
| lean-eight-workers | Same code, eight processes | 8 | 165.99 | 430.09 | 104 | 4,721 |
| lean-two-workers | Same code, two processes | 2 | 275.06 | 327.83 | 329 | 1,338 |
| final-read-run1 | Retained code, repetition | 4 | 990.12 | 1,528.47 | 129 | 825 |
| final-read-run2 | Retained code, repetition | 4 | 463.11 | 611.03 | 122 | 1,743 |

The early single-run improvement from 159.86 to 94.15 ms is encouraging but not a stable estimate: repetitions varied substantially on this shared host. WAL and increased worker count are not adopted based on these trials. An experimental asynchronous clock changed error handling and showed no demonstrated advantage (p95 240.58 and 115.81 ms); it was reverted. See the `k6-run-*`, `k6-summary-*` and `k6-database-audit-*` files for full outcomes. The previous one- and four-worker experiments remain in `k6-conditions.md`.

## Functional regression checks

`python -m pytest --cov=src.domain --cov-branch --cov-report=term-missing -q`: 93 passed; 98% combined domain coverage, 11/12 branches. `npx playwright test`: 3 passed. See `../test-evidence-performance-pytest.txt` and `../test-evidence-performance-playwright.txt`.

## Next measurement

Profile the retained code on a representative deployment, with load generation on a separate host and machine utilization recorded; compare repeated runs at the same concurrency, duration and threshold. Investigate database pool wait, thread scheduling and request processing before selecting further changes. The target must not be marked PASS until repeated relevant measurements actually meet it, with all integrity and error checks passing.

To reproduce the four-worker gate, follow the fresh-database instructions in `k6-conditions.md`; the unchanged test is `tests/nfr/quota-batch-reset.js`. Do not use a production database.

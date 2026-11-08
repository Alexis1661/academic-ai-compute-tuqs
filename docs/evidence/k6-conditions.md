# k6 reset run conditions and evidence

Observed 2026-11-08 (America/Bogota), Windows, AMD Ryzen 5 7520U (4 cores / 8 logical processors), Python 3.12.6, local k6 2.3.0, SQLite file on the same machine. Each run used a fresh, isolated database with migrations applied and no external traffic. Admin authentication and development seeding were explicitly enabled using a temporary, non-production token. No credentials are included in these artifacts.

50 continuous virtual users read balances for 5 seconds; the reset starts at t=1 second while they are active. Setup rejects fewer than 2,000 newly inserted previous-period buckets, each at 85,000 of 100,000 tokens. The script checks reset response count and time, zero HTTP read errors, and each of the 2,000 balances. Separate SQLite queries confirm actual prior and new rows, because the balance API supplies default values for missing rows. `k6` exited 99 in each run because read p95 exceeded 50 ms. These read timings do not measure admission p95 under NFR-1's 100 concurrent admission requests.

| Run | Uvicorn processes | Reset | Read p95 | Read p99 | Read errors | Physical verification | Gate |
|---|---:|---:|---:|---:|---:|---|---|
| single-worker | 1, access logs enabled | 679 ms | 661.55 ms | not recorded | 0/627 | 2,000 previous 85,000; 2,000 current 0 | FAIL p95 |
| 4workers | 4, access logs disabled | 645 ms | 428.75 ms | 608.48 ms | 0/1,378 | 2,000 previous 85,000; 2,000 current 0 | FAIL p95 |

These are distinct server configurations, so the comparison does not isolate worker count. The script enforces the original thresholds rather than relaxing them. Full console and JSON outputs and SQL audit are named `k6-run-*`, `k6-summary-*` and `k6-database-audit-*` respectively in this directory. The files establish this machine's results, not a general capacity limit.

To reproduce, start a new database, set `APP_ENV=test`, `ENABLE_TEST_SEED=true`, `ADMIN_TOKEN` to a non-production secret and `DATABASE_URL` to an isolated SQLite file. Run Alembic once, set `AUTO_MIGRATE=false`, and run `uvicorn src.main:app --host 127.0.0.1 --port 8009 --workers 4 --no-access-log --log-level warning`. In a second shell set `BASE_URL=http://127.0.0.1:8009` and the same `ADMIN_TOKEN`, then execute `k6 run --summary-export <output.json> tests/nfr/quota-batch-reset.js`. A rerun needs a fresh database. The test-seed endpoint is not for production data.

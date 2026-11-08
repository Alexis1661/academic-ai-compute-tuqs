/**
 * Story 8.5 load gate. Use ONLY an isolated, empty database.
 * Start server with ADMIN_TOKEN and ENABLE_TEST_SEED=true; provide the same
 * ADMIN_TOKEN to k6. Setup fails if exactly 2,000 rows were not newly seeded.
 * 50 active reader VUs run across the reset; teardown checks every balance.
 * For physical-row proof, inspect the database as described in the report:
 * the balance API returns a default for an absent row.
 *
 * ADMIN_TOKEN=... k6 run --summary-export docs/evidence/k6-summary.json tests/nfr/quota-batch-reset.js
 */
import http from 'k6/http';
import { check, fail } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const API = `${__ENV.BASE_URL || 'http://localhost:8000'}/api/v1`;
const COUNT = 2000;
const readLatency = new Trend('concurrent_read_latency_ms', true);
const failedReads = new Rate('concurrent_read_errors');
const resetLatency = new Trend('reset_duration_ms', true);
const resetSuccess = new Rate('reset_success');
const zeroBalanceFailures = new Counter('verification_failures');
const zeroBalancesChecked = new Counter('balances_verified');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    readers: { executor: 'constant-vus', vus: 50, duration: '5s', exec: 'readBalance' },
    reset: { executor: 'shared-iterations', vus: 1, iterations: 1, startTime: '1s', maxDuration: '10s', exec: 'resetBuckets' },
  },
  thresholds: {
    concurrent_read_latency_ms: ['p(95)<50'],
    concurrent_read_errors: ['rate==0'],
    reset_duration_ms: ['max<2000'],
    reset_success: ['rate==1'],
    verification_failures: ['count==0'],
    balances_verified: ['count==2000'],
    checks: ['rate==1'],
  },
};
function user(i) { return `bench_user_${String(i).padStart(4, '0')}`; }
function adminHeaders() { return { 'Content-Type': 'application/json', 'X-Admin-Token': __ENV.ADMIN_TOKEN }; }
function parsed(response) { try { return response.json(); } catch (_) { return {}; } }

export function setup() {
  if (!__ENV.ADMIN_TOKEN) fail('ADMIN_TOKEN must be supplied; use an isolated test service.');
  const res = http.post(`${API}/quota/cron/seed-test-buckets`, JSON.stringify({count: COUNT, token_limit: 100000, usage_percent: 0.85}), {headers: adminHeaders(), timeout: '30s'});
  const body = parsed(res);
  if (res.status !== 201 || body.seeded !== COUNT || body.tokens_used !== 85000) {
    fail(`Seed did not insert exactly ${COUNT} rows at 85%: HTTP ${res.status}, ${res.body}`);
  }
  console.log(`Seeded ${body.seeded} prior-period buckets at ${body.tokens_used} tokens, period=${body.period}`);
}

export function resetBuckets() {
  const start = Date.now();
  const res = http.post(`${API}/quota/cron/midnight-reset`, null, {headers: adminHeaders(), timeout: '10s'});
  const elapsed = Date.now() - start;
  resetLatency.add(elapsed);
  const body = parsed(res);
  const ok = check(res, {
    'reset returns 200': r => r.status === 200,
    'reset creates exactly 2000 period buckets': () => body.buckets_reset === COUNT,
    'reset elapsed < 2000 ms': () => elapsed < 2000,
  });
  resetSuccess.add(ok);
  console.log(`Reset: HTTP ${res.status}, created=${body.buckets_reset}, period=${body.period}, elapsed_ms=${elapsed}`);
}

export function readBalance() {
  const i = Math.floor(Math.random() * COUNT);
  const res = http.get(`${API}/tokens/balance/${user(i)}`, {timeout: '2s', tags: {name: 'concurrent_balance_read'}});
  readLatency.add(res.timings.duration);
  const ok = res.status === 200 && parsed(res).user_id === user(i);
  failedReads.add(!ok);
  check(res, {'concurrent read is HTTP 200 with requested user': () => ok});
}

export function teardown() {
  let bad = 0;
  for (let i = 0; i < COUNT; i++) {
    const res = http.get(`${API}/tokens/balance/${user(i)}`, {timeout: '2s', tags: {name: 'verify_balance'}});
    const body = parsed(res);
    const ok = res.status === 200 && body.user_id === user(i) && body.tokens_used === 0 && body.token_limit === 100000;
    if (!ok) { bad++; zeroBalanceFailures.add(1); }
    zeroBalancesChecked.add(1);
    check(res, {'post-reset balance is zero': () => ok});
  }
  // Ensure the zero-count metric exists even when there are no failures.
  if (!bad) zeroBalanceFailures.add(0);
  console.log(`Verified ${COUNT} API balances; failures=${bad}. Physical rows require a database audit.`);
}


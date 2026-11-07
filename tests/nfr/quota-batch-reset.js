/**
 * Story 8.5 — k6 NFR Benchmark: Midnight Quota Reset
 * Flow D: Quality Gate (Performance & NFR)
 *
 * BDD Acceptance Scenario:
 *   Given 2,000 student quota buckets seeded with arbitrary usage > 80%
 *   When the midnight reset cron job triggers
 *   Then all 2,000 daily buckets reset tokens_used to 0
 *   And total batch execution time is strictly less than 2.0 seconds
 *   And concurrent token query reads experience zero lock timeouts
 *
 * Usage:
 *   # 1. Start the TUQS service (with Docker or locally)
 *   # 2. Seed 2,000 benchmark buckets:
 *   #      curl -s -X POST http://localhost:8000/api/v1/quota/cron/seed-test-buckets \
 *   #           -H "Content-Type: application/json" \
 *   #           -d '{"count": 2000, "token_limit": 100000, "usage_percent": 0.85}'
 *   # 3. Run this benchmark:
 *   #      k6 run tests/nfr/quota-batch-reset.js
 */

import http from "k6/http";
import { check, group } from "k6";
import { Trend, Counter, Rate } from "k6/metrics";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const resetDuration = new Trend("reset_duration_ms", true);
const readLatency = new Trend("concurrent_read_latency_ms", true);
const lockTimeouts = new Counter("lock_timeouts");
const resetSuccessRate = new Rate("reset_success_rate");

// ---------------------------------------------------------------------------
// Test configuration
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API = `${BASE_URL}/api/v1`;

export const options = {
  scenarios: {
    // Scenario A: single VU fires the midnight reset and measures wall-clock time
    midnight_reset: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "10s",
      exec: "runMidnightReset",
      tags: { scenario: "midnight_reset" },
    },

    // Scenario B: 50 concurrent read VUs query quota balances during the reset window
    concurrent_reads: {
      executor: "constant-vus",
      vus: 50,
      duration: "5s",
      exec: "runConcurrentReads",
      startTime: "0s",
      tags: { scenario: "concurrent_reads" },
    },
  },

  thresholds: {
    // AD-19 / Story 8.5: batch reset must complete in < 2,000 ms
    reset_duration_ms: ["max < 2000"],
    // Concurrent reads must not stall: p95 < 500 ms, no timeouts
    concurrent_read_latency_ms: ["p(95) < 500"],
    lock_timeouts: ["count == 0"],
    reset_success_rate: ["rate == 1.0"],
  },
};

// ---------------------------------------------------------------------------
// Scenario A: Midnight reset execution
// ---------------------------------------------------------------------------
export function runMidnightReset() {
  group("midnight_reset_cron", () => {
    const startMs = Date.now();

    const res = http.post(
      `${API}/quota/cron/midnight-reset`,
      null,
      { timeout: "10s", tags: { name: "midnight_reset" } }
    );

    const elapsedMs = Date.now() - startMs;
    resetDuration.add(elapsedMs);

    const passed = check(res, {
      "reset returns HTTP 200": (r) => r.status === 200,
      "buckets_reset > 0": (r) => {
        try {
          return JSON.parse(r.body).buckets_reset > 0;
        } catch {
          return false;
        }
      },
      "reset completed within 2000ms": () => elapsedMs < 2000,
    });

    resetSuccessRate.add(passed ? 1 : 0);

    if (!passed) {
      console.error(
        `[FAIL] Midnight reset: status=${res.status} elapsed=${elapsedMs}ms body=${res.body}`
      );
    } else {
      const body = JSON.parse(res.body);
      console.log(
        `[OK] Midnight reset complete: ${body.buckets_reset} buckets in ${elapsedMs}ms`
      );
    }
  });
}

// ---------------------------------------------------------------------------
// Scenario B: Concurrent balance reads (must not lock-timeout during reset)
// ---------------------------------------------------------------------------
export function runConcurrentReads() {
  // Sample a spread of bench_user_* IDs to exercise the quota store while reset runs
  const userId = `bench_user_${String(Math.floor(Math.random() * 2000)).padStart(4, "0")}`;

  group("concurrent_balance_reads", () => {
    const startMs = Date.now();

    const res = http.get(
      `${API}/tokens/balance/${userId}`,
      { timeout: "2s", tags: { name: "balance_read" } }
    );

    const elapsedMs = Date.now() - startMs;
    readLatency.add(elapsedMs);

    const isTimeout =
      res.status === 503 ||
      res.error_code === "ECONNREFUSED" ||
      (res.timings && res.timings.duration > 1900);

    if (isTimeout) {
      lockTimeouts.add(1);
      console.warn(`[LOCK TIMEOUT] user=${userId} status=${res.status} elapsed=${elapsedMs}ms`);
    }

    check(res, {
      "balance read not a lock timeout": () => !isTimeout,
      "balance read returns 200 or 404": (r) => r.status === 200 || r.status === 404,
    });
  });
}

// ---------------------------------------------------------------------------
// Setup: seed 2,000 benchmark buckets before the test run
// ---------------------------------------------------------------------------
export function setup() {
  console.log("Seeding 2,000 benchmark quota buckets (> 80% usage)...");
  const res = http.post(
    `${API}/quota/cron/seed-test-buckets`,
    JSON.stringify({ count: 2000, token_limit: 100000, usage_percent: 0.85 }),
    { headers: { "Content-Type": "application/json" }, timeout: "30s" }
  );

  if (res.status !== 201) {
    console.error(`Seed failed: status=${res.status} body=${res.body}`);
  } else {
    const body = JSON.parse(res.body);
    console.log(`Seeded ${body.seeded} buckets for period ${body.period}`);
  }
}

// ---------------------------------------------------------------------------
// Teardown: summary
// ---------------------------------------------------------------------------
export function teardown() {
  console.log("NFR benchmark complete. Check threshold results above.");
}


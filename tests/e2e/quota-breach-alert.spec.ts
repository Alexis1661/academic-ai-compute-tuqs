import { test, expect } from "@playwright/test";
import { UsageDashboardPage } from "./pages/UsageDashboardPage";

/**
 * Story 8.6 — Real-Time Usage Ledger & Quota Breach Alert Banner E2E
 * Flow E: Playwright E2E with Page Object Model
 *
 * Mandated Scenario:
 *   Given Sam is viewing his Token Usage Dashboard with 95,000 of 100,000 tokens used
 *   When a simulated background job consumes an additional 6,000 tokens
 *   And the dashboard refreshes its ledger state
 *   Then the progress bar turns solid Red at 100%
 *   And an urgent alert banner displays:
 *     "Daily Quota Depleted: Model Access Paused Until Midnight"
 */

const BASE_URL = process.env.BASE_URL || "http://localhost:8000";
const API_URL  = `${BASE_URL}/api/v1`;

// Unique student ID per test to avoid state pollution between runs
const testUserId = () => `sam_${Date.now()}`;

/** Helper: seed a user quota via the consumption event ingestion endpoint */
async function seedUsage(
  request: import("@playwright/test").APIRequestContext,
  userId: string,
  promptTokens: number,
  completionTokens: number
) {
  const resp = await request.post(`${API_URL}/tokens/events`, {
    data: {
      user_id: userId,
      subject_id: "E2E-TEST",
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
    },
  });
  expect(resp.ok(), `Failed to seed tokens for ${userId}: ${resp.status()}`).toBeTruthy();
}

test.describe("Story 8.6: Real-Time Usage Ledger & Quota Breach Alert Banner", () => {
  test(
    "Scenario: Quota meter turns red and displays breach banner at 100% consumption",
    async ({ page, request }) => {
      const studentId = testUserId();
      const dashboard = new UsageDashboardPage(page);

      // ── Given: Sam views dashboard with 95,000 / 100,000 tokens consumed (95%) ──
      await seedUsage(request, studentId, 95_000, 0);

      await dashboard.navigate(studentId, BASE_URL);

      // Verify initial amber state (95% is in the 80–99% warning window)
      await expect(dashboard.tokensUsedValue).toHaveText("95,000");
      await expect(dashboard.tokenLimitValue).toHaveText("100,000");
      await expect(dashboard.tokensRemainingValue).toHaveText("5,000");
      expect(await dashboard.getMeterState()).toBe("amber");

      // Soft-warning banner is visible; breach banner is not yet shown
      await dashboard.expectWarningBannerVisible();
      await dashboard.expectBreachBannerHidden();

      // ── When: simulated background job consumes an additional 6,000 tokens ────────
      // Total usage becomes 95,000 + 6,000 = 101,000 (100% ceiling breached)
      await seedUsage(request, studentId, 6_000, 0);

      // ── And: the dashboard refreshes its ledger state ──────────────────────────
      // The dashboard polls every 5 s; we wait for the reactive state transition
      await dashboard.waitForMeterState("red", 12_000);

      // ── Then: the progress bar turns solid Red at 100% ──────────────────────────
      expect(await dashboard.getMeterState()).toBe("red");
      const rgbColor = await dashboard.getMeterColor();
      // #d32f2f in RGB is rgb(211, 47, 47)
      expect(rgbColor).toMatch(/rgb\(211,\s*47,\s*47\)/);

      // ── And: an urgent alert banner displays the exact required text ───────────
      await dashboard.expectBreachBannerVisible();
      const bannerTitle = await dashboard.getBreachBannerTitle();
      expect(bannerTitle).toBe(
        "Daily Quota Depleted: Model Access Paused Until Midnight"
      );

      // Soft-warning banner should be dismissed in favour of the urgent breach banner
      await dashboard.expectWarningBannerHidden();

      // Accessibility: breach banner must have role="alert" for assistive technology
      await dashboard.expectBreachBannerHasAlertRole();
    }
  );

  test(
    "Meter colour transitions: Green (< 80%) → Amber (>= 80%)",
    async ({ page, request }) => {
      const studentId = testUserId();
      const dashboard = new UsageDashboardPage(page);

      // Start at 50% usage: Green
      await seedUsage(request, studentId, 50_000, 0);
      await dashboard.navigate(studentId, BASE_URL);

      expect(await dashboard.getMeterState()).toBe("green");
      const greenColor = await dashboard.getMeterColor();
      expect(greenColor).toMatch(/rgb\(46,\s*125,\s*50\)/); // #2e7d32
      await dashboard.expectWarningBannerHidden();
      await dashboard.expectBreachBannerHidden();

      // Consume up to 82%: should transition to Amber
      await seedUsage(request, studentId, 32_000, 0);
      await dashboard.waitForMeterState("amber", 12_000);

      expect(await dashboard.getMeterState()).toBe("amber");
      const amberColor = await dashboard.getMeterColor();
      expect(amberColor).toMatch(/rgb\(255,\s*143,\s*0\)/); // #ff8f00
      await dashboard.expectWarningBannerVisible();
      await dashboard.expectBreachBannerHidden();
    }
  );

  test(
    "Fresh student shows 0 tokens used and green meter",
    async ({ page }) => {
      const studentId = testUserId();
      const dashboard = new UsageDashboardPage(page);

      await dashboard.navigate(studentId, BASE_URL);

      await expect(dashboard.tokensUsedValue).toHaveText("0");
      expect(await dashboard.getMeterState()).toBe("green");
      await dashboard.expectWarningBannerHidden();
      await dashboard.expectBreachBannerHidden();
    }
  );
});

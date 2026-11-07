import type { Page, Locator } from "@playwright/test";

/**
 * Story 8.6 — Page Object Model: UsageDashboardPage
 * Flow E: Playwright E2E with Page Object Model
 *
 * Models the Token Usage Dashboard at /student/quota:
 *   - Token meter bar (colour-coded: Green → Amber → Red)
 *   - Numeric counters (tokens used, limit, remaining)
 *   - 80% soft-warning banner
 *   - 100% breach alert banner ("Daily Quota Depleted: Model Access Paused Until Midnight")
 *
 * Usage:
 *   const page = new UsageDashboardPage(playwrightPage);
 *   await page.navigate("sam");
 *   await page.waitForMeterColor("red");
 *   await page.expectBreachBannerVisible();
 */
export class UsageDashboardPage {
  readonly page: Page;

  // ── Meter bar ────────────────────────────────────────────────────────────
  /** The coloured fill bar inside the progress track */
  readonly meterBar: Locator;
  /** The ARIA progressbar track (wrapper) */
  readonly meterTrack: Locator;
  /** The percentage label (e.g. "95.00%") */
  readonly percentLabel: Locator;

  // ── Numeric counters ─────────────────────────────────────────────────────
  readonly tokensUsedValue: Locator;
  readonly tokenLimitValue: Locator;
  readonly tokensRemainingValue: Locator;

  // ── Banners ───────────────────────────────────────────────────────────────
  /**
   * Urgent alert banner displayed at 100% quota (Story 8.6 BDD):
   *   "Daily Quota Depleted: Model Access Paused Until Midnight"
   */
  readonly breachBanner: Locator;
  readonly breachBannerTitle: Locator;
  /** Soft warning banner shown between 80–99% consumption */
  readonly warningBanner: Locator;
  readonly warningMessage: Locator;

  constructor(page: Page) {
    this.page = page;

    this.meterBar          = page.locator("#meter-bar");
    this.meterTrack        = page.locator("[role='progressbar']");
    this.percentLabel      = page.locator("#percent-label");

    this.tokensUsedValue      = page.locator("#tokens-used-value");
    this.tokenLimitValue      = page.locator("#token-limit-value");
    this.tokensRemainingValue = page.locator("#tokens-remaining-value");

    this.breachBanner      = page.locator("#quota-breach-banner");
    this.breachBannerTitle = page.locator("#breach-title");
    this.warningBanner     = page.locator("#quota-warning-banner");
    this.warningMessage    = page.locator("#warning-message");
  }

  // ── Navigation ───────────────────────────────────────────────────────────

  /** Navigate to the quota dashboard for `userId` and wait for the meter bar. */
  async navigate(userId: string = "sam", baseUrl: string = "http://localhost:8000"): Promise<void> {
    await this.page.goto(`${baseUrl}/student/quota?user_id=${encodeURIComponent(userId)}`);
    await this.meterBar.waitFor({ state: "attached" });
  }

  // ── Meter colour helpers ──────────────────────────────────────────────────

  /**
   * Returns the current `data-state` attribute of the meter bar.
   * Possible values: "green" | "amber" | "red"
   */
  async getMeterState(): Promise<string> {
    return (await this.meterBar.getAttribute("data-state")) ?? "unknown";
  }

  /**
   * Returns the computed background-color CSS value of the meter bar
   * (e.g. "rgb(46, 125, 50)" for green).
   */
  async getMeterColor(): Promise<string> {
    return this.page.evaluate(() => {
      const bar = document.getElementById("meter-bar");
      return bar ? getComputedStyle(bar).backgroundColor : "";
    });
  }

  /**
   * Waits (up to `timeout` ms) until the meter bar's data-state matches `expectedState`.
   * Used to verify the Green → Amber → Red colour transition.
   */
  async waitForMeterState(
    expectedState: "green" | "amber" | "red",
    timeout: number = 15_000
  ): Promise<void> {
    await this.page.waitForFunction(
      (state) => {
        const bar = document.getElementById("meter-bar");
        return bar?.dataset.state === state;
      },
      expectedState,
      { timeout }
    );
  }

  // ── Numeric counter helpers ───────────────────────────────────────────────

  /** Returns the displayed "Tokens Used" value as a number (strips commas). */
  async getTokensUsed(): Promise<number> {
    const text = await this.tokensUsedValue.innerText();
    return parseInt(text.replace(/,/g, ""), 10);
  }

  /** Returns the displayed "Daily Limit" value as a number. */
  async getTokenLimit(): Promise<number> {
    const text = await this.tokenLimitValue.innerText();
    return parseInt(text.replace(/,/g, ""), 10);
  }

  /** Returns the displayed "Remaining" value as a number. */
  async getTokensRemaining(): Promise<number> {
    const text = await this.tokensRemainingValue.innerText();
    return parseInt(text.replace(/,/g, ""), 10);
  }

  /** Returns the percentage label text (e.g. "95.00%"). */
  async getPercentText(): Promise<string> {
    return (await this.percentLabel.innerText()).trim();
  }

  // ── Banner assertions ─────────────────────────────────────────────────────

  /** Asserts that the breach banner is visible and contains the required message text. */
  async expectBreachBannerVisible(): Promise<void> {
    await this.breachBanner.waitFor({ state: "visible" });
  }

  /** Asserts that the breach banner is hidden. */
  async expectBreachBannerHidden(): Promise<void> {
    await this.breachBanner.waitFor({ state: "hidden" });
  }

  /** Returns the visible text of the breach banner title. */
  async getBreachBannerTitle(): Promise<string> {
    return (await this.breachBannerTitle.innerText()).trim();
  }

  /** Asserts that the soft-warning banner is visible. */
  async expectWarningBannerVisible(): Promise<void> {
    await this.warningBanner.waitFor({ state: "visible" });
  }

  /** Asserts that the soft-warning banner is hidden. */
  async expectWarningBannerHidden(): Promise<void> {
    await this.warningBanner.waitFor({ state: "hidden" });
  }

  // ── ARIA accessibility helpers ────────────────────────────────────────────

  /** Returns the ARIA aria-valuenow attribute of the meter track. */
  async getAriaValueNow(): Promise<string> {
    return (await this.meterTrack.getAttribute("aria-valuenow")) ?? "";
  }

  /** Asserts the breach banner has role="alert" for screen reader accessibility. */
  async expectBreachBannerHasAlertRole(): Promise<void> {
    await this.page.locator("[role='alert']#quota-breach-banner").waitFor({ state: "visible" });
  }
}


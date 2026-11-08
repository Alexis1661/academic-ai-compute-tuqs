import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const externalUrl = process.env.BASE_URL;
export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  retries: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: externalUrl || "http://localhost:8000", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: externalUrl ? undefined : {
    command: "python -m uvicorn src.main:app --host 127.0.0.1 --port 8000",
    cwd: path.resolve(__dirname, "../.."),
    env: { DATABASE_URL: "sqlite:///./playwright-e2e.db", AUTO_MIGRATE: "true" },
    url: "http://127.0.0.1:8000/api/v1/health",
    reuseExistingServer: false,
    timeout: 30000,
  },
});

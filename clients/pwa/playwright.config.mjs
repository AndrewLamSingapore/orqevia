import { defineConfig } from "@playwright/test";

const port = Number(process.env.PWA_TEST_PORT || 4173);

export default defineConfig({
  testDir: "./browser-tests",
  outputDir: "./browser-results/artifacts",
  fullyParallel: false,
  workers: process.env.CI ? 1 : 2,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: Boolean(process.env.CI),
  failOnFlakyTests: Boolean(process.env.CI),
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [
    ["line"],
    ["json", { outputFile: "browser-results/results.json" }],
    ["html", { outputFolder: "browser-results/html", open: "never" }],
  ],
  use: {
    baseURL: `http://localhost:${port}`,
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ignoreHTTPSErrors: false,
  },
  webServer: {
    command: "node browser-test-server.mjs",
    url: `http://localhost:${port}/pwa/`,
    timeout: 20_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
});

import { expect, test } from "@playwright/test";
import { mockSession, waitForSession } from "./fixtures.mjs";

test("compact iPhone-sized God's Eye loads records without auto-starting WebGL", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(/\/api\/orqevia\/intelligence\/health(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    }),
  );
  await page.route(/\/api\/orqevia\/intelligence\/geo\/events(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        records: [
          {
            event_id: "compact-safety-fixture",
            place: "Compact fixture",
            magnitude: 5,
            location: { lat: 1.35, lon: 103.82 },
            source_url: "https://earthquake.usgs.gov/example",
            observed_at: "2026-10-20T08:00:00Z",
            ingested_at: "2026-10-20T08:05:00Z",
          },
        ],
      }),
    }),
  );
  await page.route(/\/api\/orqevia\/intelligence\/detection\/alerts(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ alerts: [] }),
    }),
  );
  for (const endpoint of ["sources", "history/timeline"]) {
    await page.route(
      new RegExp(`/api/orqevia/intelligence/${endpoint}(?:\\?.*)?$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        }),
    );
  }
  await page.route(/\/interface\/v1\/telemetry(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        observed_at: new Date().toISOString(),
        freshness_seconds: 60,
        agents: [],
        metrics: [],
      }),
    }),
  );
  await page.route(/\/pwa\/agent-readiness\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ agents: {} }),
    }),
  );
  await page.route(/\/pwa\/vendor\/maplibre-gl\.mjs(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 503,
      contentType: "text/plain",
      body: "controlled map asset failure",
    }),
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pwa/");
  await waitForSession(page);
  await page.locator('.function-grid [data-view="gods-eye"]').click();

  await expect(page.locator("#intelligence-title")).toHaveText("God's Eye");
  await expect(page.locator("#intelligence-state")).toHaveAttribute("data-state", "ready");
  await expect(
    page.locator("#intelligence-content summary").filter({ hasText: "Compact fixture" }),
  ).toBeVisible();
  await expect(
    page.getByText("Interactive map startup is paused on this compact screen", {
      exact: false,
    }),
  ).toBeVisible();
  const mapButton = page.getByRole("button", { name: "Show interactive map" });
  await expect(mapButton).toBeVisible();
  await mapButton.click();
  await expect(page.getByText("Interactive map unavailable", { exact: false })).toBeVisible();
  await expect(page.locator("#intelligence-workspace")).toBeVisible();
});

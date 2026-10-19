import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, mockSession, waitForSession } from "./fixtures.mjs";

test.beforeEach(async ({ page }) => {
  await mockSession(page);
});

test("desktop shell, manifest and primary navigation are functional", async ({ page }) => {
  await page.goto("/pwa/");
  await waitForSession(page);
  await expect(page).toHaveTitle(/ORQEVIA/i);
  await expect(page.locator("#dashboard")).toBeVisible();
  await expect(page.locator(".desktop-navigation")).toBeVisible();
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/pwa/manifest.webmanifest");
  await expectNoHorizontalOverflow(page);

  await page.locator('.desktop-navigation [data-view="agents"]').click();
  await expect(page.locator("#capability-view")).toBeVisible();
  await expect(page.locator("#capability-title")).toHaveText("Agents");
  await expect(page).toHaveURL(/view=agents/);
});

test("mobile shell has safe in-flow controls and no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pwa/");
  await waitForSession(page);
  await expect(page.locator(".mobile-navigation")).toBeVisible();
  await expect(page.locator(".desktop-navigation")).toBeHidden();
  await expectNoHorizontalOverflow(page);

  await page.locator('.mobile-navigation [data-view="agents"]').click();
  await expect(page.locator("#capability-view")).toBeVisible();
  await expect(page.locator("#capability-title")).toHaveText("Agents");
  await expectNoHorizontalOverflow(page);
});

test("primary controls expose labels and unique ids", async ({ page }) => {
  await page.goto("/pwa/");
  await waitForSession(page);
  const audit = await page.evaluate(() => {
    const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
    const unlabeled = [...document.querySelectorAll("button")]
      .filter((button) => !(button.textContent || "").trim() && !button.getAttribute("aria-label"))
      .map((button) => button.outerHTML.slice(0, 160));
    return { duplicates: [...new Set(duplicates)], unlabeled };
  });
  expect(audit.duplicates).toEqual([]);
  expect(audit.unlabeled).toEqual([]);
});

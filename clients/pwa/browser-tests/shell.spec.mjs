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
  for (const panel of ['system-overview', 'live-system-health', 'active-tasks', 'live-activity']) {
    await expect(page.locator('#' + panel)).toBeVisible();
  }
  await expect(page.locator('#ready-agent-count')).toBeVisible();

  await page.locator('.desktop-navigation [data-view="operations"]').click();
  await expect(page.locator("#operations-view")).toBeVisible();
  await expect(page).toHaveURL(/view=operations/);
  await expect(page.getByRole('heading', { name: 'Probabilistic Intelligence Fabric (PIF)', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Model Efficiency Layer (MEL)', exact: true })).toBeVisible();
  await page.locator('#fabric-console [data-intelligence-jump="pif"]').click();
  await expect(page.locator('#pif-heading')).toBeFocused();
  await page.locator('#fabric-console [data-intelligence-jump="mel"]').click();
  await expect(page.locator('#mel-heading')).toBeFocused();

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

  const operations = page.locator('.mobile-navigation [data-view="operations"]');
  await expect(operations).toBeVisible();
  await expect(operations).toHaveAccessibleName("Operations Board");
  for (const width of [320, 390, 760]) {
    await page.setViewportSize({ width, height: 844 });
    await expectNoHorizontalOverflow(page);
    for (const panel of ['system-overview', 'live-system-health', 'active-tasks', 'live-activity']) {
      await expect(page.locator('#' + panel)).toBeVisible();
    }
    await expect(page.locator('#ready-agent-count')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const bottom = document.querySelector('.dashboard-bottom').getBoundingClientRect().bottom;
      const shortcuts = document.querySelector('.function-grid').getBoundingClientRect().top;
      const tabs = document.querySelector('.mobile-navigation');
      return { factsBeforeShortcuts: bottom <= shortcuts, fixedTabs: getComputedStyle(tabs).position };
    });
    expect(geometry.factsBeforeShortcuts).toBe(true);
    expect(geometry.fixedTabs).toBe('fixed');
    const targets = await page.locator('.mobile-navigation > button').evaluateAll((buttons) =>
      buttons.map((button) => {
        const box = button.getBoundingClientRect();
        return { width: box.width, height: box.height };
      }),
    );
    expect(targets).toHaveLength(6);
    expect(targets.every((box) => box.width >= 44 && box.height >= 44)).toBe(true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await operations.click();
  await expect(page.locator("#operations-view")).toBeVisible();
  await expect(page).toHaveURL(/view=operations/);
  await expect(page.locator('#mobile-more-dialog')).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Probabilistic Intelligence Fabric (PIF)', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Model Efficiency Layer (MEL)', exact: true })).toBeVisible();
  const moduleOrder = await page.evaluate(() => document.getElementById('intelligence-capabilities').getBoundingClientRect().top < document.getElementById('fabric-console').getBoundingClientRect().top);
  expect(moduleOrder).toBe(true);
  await page.locator('#fabric-console [data-intelligence-jump="pif"]').click();
  await expect(page.locator('#pif-heading')).toBeFocused();
  await page.locator('#fabric-console [data-intelligence-jump="mel"]').click();
  await expect(page.locator('#mel-heading')).toBeFocused();

  await page.locator('#mobile-more-open').click();
  await expect(page.locator('#mobile-more-dialog [data-view="operations"]')).toBeVisible();
  await expect(page.locator('#mobile-more-dialog a[href="/pwa/projects.html"]')).toBeVisible();
  const desktopViews = await page.locator('.desktop-navigation [data-view]').evaluateAll((buttons) => buttons.map((button) => button.dataset.view));
  const mobileViews = await page.locator('#mobile-more-dialog [data-view]').evaluateAll((buttons) => buttons.map((button) => button.dataset.view));
  for (const view of desktopViews) expect(mobileViews).toContain(view);
  for (const panel of ['system-overview', 'live-system-health', 'active-tasks', 'live-activity']) {
    await expect(page.locator(`#mobile-more-dialog [data-panel="${panel}"]`)).toBeVisible();
  }
  await page.locator('#mobile-more-dialog [data-view="agents"]').click();
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

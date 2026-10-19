import { expect, test } from "@playwright/test";
import { mockSession, mockTaskApi, waitForSession } from "./fixtures.mjs";

test("an objective is submitted through the existing session boundary and reaches a terminal result", async ({
  page,
}) => {
  const observations = {};
  await mockSession(page);
  await mockTaskApi(page, observations);
  await page.goto("/pwa/");
  await waitForSession(page);

  await page.locator('.desktop-navigation [data-new-objective]').click();
  await expect(page.locator("#objective-form")).toBeVisible();
  await page.locator("#objective").fill("Verify the ORQEVIA browser workflow");
  await page.locator("#submit-button").click();

  await expect(page.locator("#active-section")).toBeVisible();
  await expect(page.locator("#task-result")).toContainText("Browser verification result.");
  await expect(page.locator("#task-id")).toContainText("task-browser-verification");
  expect(observations.submitBody).toEqual({
    objective: "Verify the ORQEVIA browser workflow",
    uploaded_artifact_ids: [],
  });
  expect(observations.submitHeaders["x-orqevia-pwa"]).toBe("1");
  expect(observations.submitHeaders["idempotency-key"]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  expect(observations.submitHeaders.authorization).toBeUndefined();
  expect(observations.submitHeaders.cookie).toBeUndefined();
});

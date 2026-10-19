import { expect } from "@playwright/test";

export const PROTOCOL = "orqevia.interface.v1";
export const TASK_ID = "task-browser-verification";
export const EVENT_ID = "a".repeat(64);

export function sessionBody() {
  return {
    protocol: PROTOCOL,
    authenticated: true,
    clientId: "browser-owner",
    role: "OWNER",
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };
}

export async function mockSession(page) {
  await page.addInitScript(() => {
    globalThis.__ORQEVIA_TEST_SUPPRESS_CONTROLLER_RELOAD__ = true;
  });
  await page.route(/\/pwa\/api\/session(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify(sessionBody()),
    }),
  );
}

export async function waitForSession(page) {
  await expect(page.locator("#connection-label")).toContainText("Connected to ORQEVIA");
}

export async function mockTaskApi(page, observations = {}) {
  const task = {
    task_id: TASK_ID,
    revision: 1,
    state: "COMPLETED",
    updated_at: "2026-10-19T01:00:00Z",
    result: { text: observations.resultText || "Browser verification result." },
    steps: [
      {
        revision: 1,
        job: { status: "COMPLETED", agent: "a01" },
      },
    ],
  };
  await page.route(/\/interface\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = {
      "X-ORQEVIA-Protocol": PROTOCOL,
      "Access-Control-Expose-Headers": "X-ORQEVIA-Protocol",
      "Cache-Control": "no-store",
    };
    if (request.method() === "POST" && url.pathname === "/interface/v1/objectives") {
      observations.submitHeaders = await request.allHeaders();
      observations.submitBody = JSON.parse(request.postData() || "{}");
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        headers,
        body: JSON.stringify(task),
      });
    }
    if (url.pathname === `/interface/v1/tasks/${TASK_ID}/events`) {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers,
        body: `id: ${EVENT_ID}\ndata: ${JSON.stringify(task)}\n\n`,
      });
    }
    if (url.pathname === `/interface/v1/tasks/${TASK_ID}`) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify(task),
      });
    }
    if (url.pathname === `/interface/v1/tasks/${TASK_ID}/artifacts`) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          artifacts: [],
          next_offset: null,
          latest_result_artifact_id: null,
          revision: 1,
        }),
      });
    }
    return route.fulfill({
      status: 404,
      contentType: "application/json",
      headers,
      body: JSON.stringify({ error: "fixture_not_found" }),
    });
  });
}

export async function expectNoHorizontalOverflow(page) {
  const sizes = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(sizes.document, JSON.stringify(sizes)).toBeLessThanOrEqual(sizes.viewport + 1);
  expect(sizes.body, JSON.stringify(sizes)).toBeLessThanOrEqual(sizes.viewport + 1);
}

import { test, expect } from "@playwright/test";

const baseUrl = process.env.CC_BASE_URL || "";
const fixtureUrl = process.env.CC_SCREEN_POP_FIXTURE_URL || "";
const forbiddenHosts = new Set([
  "api.codestra.co",
  "auth.codestra.co",
  "codestra.co",
  "65.109.65.169",
  "65.21.67.207",
  "37.27.128.39",
]);

function assertIsolatedTarget(value) {
  const target = new URL(value);
  if (forbiddenHosts.has(target.hostname)) {
    throw new Error(`Production or infrastructure target is forbidden: ${target.hostname}`);
  }
  const allowed =
    target.hostname === "localhost" ||
    target.hostname === "127.0.0.1" ||
    target.hostname.startsWith("staging.") ||
    target.hostname.includes("isolated-staging") ||
    target.hostname.endsWith(".test");
  if (!allowed) {
    throw new Error(`Target is not an approved isolated environment: ${target.hostname}`);
  }
}

if (baseUrl) assertIsolatedTarget(baseUrl);
if (fixtureUrl) assertIsolatedTarget(fixtureUrl);

test.describe("Codestra contact-center screen-pop certification", () => {
  test.skip(!baseUrl || !fixtureUrl, "Isolated staging URLs are required explicitly.");

  test("restores an authorized active interaction and enforces wrap-up", async ({ page }) => {
    await page.goto(fixtureUrl);
    await expect(page.locator('[data-testid="cc-agent-workspace"]')).toBeVisible();
    await expect(page.locator('[data-testid="cc-active-interaction"]')).toBeVisible();
    await page.reload();
    await expect(page.locator('[data-testid="cc-active-interaction"]')).toBeVisible();
    await expect(page.locator('[data-testid="cc-return-ready"]')).toBeDisabled();
    await page.locator('[data-testid="cc-disposition"]').selectOption({ index: 1 });
    await page.locator('[data-testid="cc-wrapup-notes"]').fill("Synthetic certification fixture.");
    await page.locator('[data-testid="cc-save-wrapup"]').click();
    await expect(page.locator('[data-testid="cc-return-ready"]')).toBeEnabled();
  });
});

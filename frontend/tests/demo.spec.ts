import { test, expect } from "@playwright/test";
import path from "node:path";
test("sales upload → validation → evidence → correction → replay → audit", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Your data, at a glance." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add dataset", exact: true }).click();
  await page
    .getByLabel("Upload CSV")
    .setInputFiles(path.resolve("../demo-data/synthetic-demo.csv"));
  await expect(
    page.getByRole("heading", { name: "synthetic-demo.csv", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Preview your input", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save & start validation" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("completed with errors", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await expect(
    page.getByRole("dialog").getByText("32", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog").getByText("8", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review rejected rows" }).click();
  await page.getByLabel("Filter failure reason").selectOption("non_null");
  await expect(
    page.getByRole("button", { name: "Review", exact: true }),
  ).toHaveCount(2);
  await page
    .getByRole("button", { name: "Review", exact: true })
    .first()
    .click();
  await expect(page.locator(".evidence")).toContainText('"customer_id": ""');
  await page.getByLabel("Correction customer_id").fill("CUS-CORRECTED");
  await page
    .getByRole("button", { name: "Validate & save correction" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.locator("input[type=checkbox]:enabled").first().check();
  await page.getByRole("button", { name: "Replay 1", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByText("completed", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await expect(
    page.getByRole("dialog").getByText("accepted", { exact: true }),
  ).toBeVisible();
  const replayLabel = await page
    .getByRole("dialog")
    .getByRole("heading", { level: 2 })
    .textContent();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Audit trail", exact: true }).click();
  await expect(
    page
      .locator(".audit-event")
      .filter({ hasText: "replay / accepted" })
      .filter({ hasText: replayLabel! }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.screenshot({ path: "../docs/dashboard.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../docs/dashboard-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});

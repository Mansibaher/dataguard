import { test, expect } from "@playwright/test";
test("offline HTTP connector imports paginated synthetic records", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Your data, at a glance." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add dataset", exact: true }).click();
  await page.getByRole("button", { name: "Import source" }).click();
  await expect(
    page.getByRole("heading", { name: "HTTP sales · demo", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole("dialog").getByText("240 rows", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save & start validation" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("completed with errors", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await expect(
    page.getByRole("dialog").getByText("236", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
});

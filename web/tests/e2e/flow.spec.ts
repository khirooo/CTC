import { test, expect } from '@playwright/test';

test('sign in → dashboard → marketplace → history → theme toggle', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText(/How CTC works/i)).toBeVisible();

  // The landing's CTA starts the GHE OAuth flow.
  await page.getByRole('button', { name: /continue with github enterprise/i }).first().click();
  await expect(page.getByText(/Credit marketplace/i)).toBeVisible();

  // Sidebar nav items are NavLink (anchor) elements, not buttons
  await page.getByRole('link', { name: /Marketplace/i }).click();
  await expect(page.getByText('Lena Hoffmann')).toBeVisible();

  await page.getByRole('link', { name: /History/i }).click();
  await expect(page.getByRole('button', { name: /May 2026/i })).toBeVisible();

  await page.getByTitle(/Toggle theme/i).click(); // does not crash
});

test('marketplace donation advances a request to fulfilled in the browser', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /continue with github enterprise/i }).first().click();
  await page.getByRole('link', { name: /Marketplace/i }).click();

  // Lena Hoffmann's seeded request starts at 35 / 60. A "Chip in 25 →" click
  // must advance it to 60 / 60 (covered) — proving button → api.donate →
  // reload → re-render all work end-to-end in a real browser.
  const card = page.locator('[data-request-card]', { hasText: 'Lena Hoffmann' });
  await expect(card.getByText('35.00 AIU / 60.00 AIU')).toBeVisible();
  await card.getByRole('button', { name: /chip in/i }).click();
  await expect(card.getByText('60.00 AIU / 60.00 AIU')).toBeVisible();
  // Once fully covered the request is closed → the Chip in button is removed.
  await expect(card.getByRole('button', { name: /chip in/i })).toHaveCount(0);
});

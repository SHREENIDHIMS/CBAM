import { expect, test } from '@playwright/test'

test('development preview displays the synthetic HMRC reports without sign-in', async ({
  page,
}) => {
  await page.goto('/demo/hmrc')

  await expect(page.getByRole('heading', { name: 'HMRC customs data sample' })).toBeVisible()
  await expect(page.getByText('Synthetic data', { exact: true })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Import items sample data' })).toContainText(
    '7208100000',
  )
  await expect(page.getByRole('table', { name: 'Import items sample data' })).toContainText(
    '7601100000',
  )

  await page.getByRole('tab', { name: /Declaration header/ }).click()
  await expect(page.getByRole('table', { name: 'Declaration header sample data' })).toContainText(
    'GB123456789012',
  )

  await page.getByRole('tab', { name: /Tax lines/ }).click()
  await expect(page.getByRole('table', { name: 'Tax lines sample data' })).toContainText('250.00')
  await page.getByLabel('Show all columns').check()
  await expect(page.getByRole('columnheader', { name: 'Tax Type 12' })).toBeVisible()
})

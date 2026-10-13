import { expect, test } from '@playwright/test'
import path from 'node:path'

// The admin tightens a rule, uploads a receipt, and reviews what the rule sends to the queue.
// Credentials come from CI (manage.py create_reviewer); the models are the stand-in in e2e/.
const USER = process.env.E2E_USER ?? 'admin'
const PASSWORD = process.env.E2E_PASSWORD ?? 'e2e-review-password'
const RECEIPT = path.resolve(import.meta.dirname, '../../e2e/receipt.png')

test('a rule sends a receipt to review and a reviewer approves it', async ({ page }) => {
  await test.step('sign in', async () => {
    await page.goto('/')
    await page.getByLabel('Username').fill(USER)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Review queue' })).toBeVisible()
  })

  await test.step('publish a lower amount limit', async () => {
    await page.getByRole('link', { name: 'Rules' }).click()
    await page.getByRole('button', { name: 'Edit rules' }).click()
    const editor = page.getByLabel('Rules (JSON)')
    const rules = JSON.parse(await editor.inputValue()) as { id: string; max?: number }[]
    rules.find((r) => r.id === 'under-limit')!.max = 10000
    await editor.fill(JSON.stringify(rules, null, 2))
    await page.getByLabel('What changed?').fill('Review anything over 10,000')
    await page.getByRole('button', { name: /Publish version/ }).click()
    await expect(page.getByText('Total is at most 10,000')).toBeVisible()
  })

  await test.step('upload a receipt', async () => {
    await page.getByRole('link', { name: 'Documents' }).click()
    await page.getByLabel('Choose a document to upload').setInputFiles(RECEIPT)
    await expect(page.getByText('Uploaded receipt.png')).toBeVisible()
  })

  await test.step('the worker sends it to review because of the new rule', async () => {
    await page.getByRole('link', { name: /Queue/ }).click()
    const queue = page.getByRole('region', { name: 'Review queue' })
    await expect(queue).toBeVisible()
    // The queue refreshes every 10 seconds; the worker needs a moment to read the receipt.
    await expect(queue.getByRole('link', { name: 'receipt.png' })).toBeVisible({ timeout: 60_000 })
    await expect(queue.getByText('under-limit')).toBeVisible()
  })

  await test.step('review and approve it', async () => {
    await page.getByRole('button', { name: 'Review next' }).click()
    await expect(page.getByText('total 36,000 over the 10,000 limit')).toBeVisible()
    await expect(page.getByLabel('Total', { exact: true })).toHaveValue('36000')
    await page.getByRole('button', { name: 'Approve & next' }).click()
    await expect(page.getByText('Nothing to review.', { exact: false })).toBeVisible()
  })

  await test.step('the decision and its history are recorded', async () => {
    await page.getByRole('link', { name: 'Documents' }).click()
    await page.getByRole('link', { name: 'receipt.png' }).click()
    await expect(page.getByRole('heading', { name: `Approved by ${USER}` })).toBeVisible()
    await expect(page.getByText('Sent to review')).toBeVisible()
    await expect(page.getByText('Opened for review')).toBeVisible()
  })
})

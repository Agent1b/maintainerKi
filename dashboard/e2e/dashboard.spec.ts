import { expect, test } from '@playwright/test'

test('maintainer core flow covers auth, inbox, detail, feedback, and logout', async ({
  page,
}) => {
  await page.goto('/')

  await test.step('sign in through the maintainer login screen', async () => {
    await expect(page.getByRole('heading', { name: 'Maintainer sign-in' })).toBeVisible()
    await page.getByLabel('Username').fill('admin')
    await page.getByLabel('Password').fill('let-me-in')
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page.getByRole('heading', { name: 'Maintainer inbox dashboard' })).toBeVisible()
    await expect(
      page.getByRole('button', { name: /Login button breaks on mobile Safari/i }),
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: /Throttle webhook replay retries/i }),
    ).toBeVisible()
  })

  await test.step('exercise populated and empty inbox states', async () => {
    await page.getByLabel('Search').fill('no-matches-for-this-query')
    await expect(page.getByText('No matches.')).toBeVisible()
    await expect(page.locator('.detail-card')).toContainText('Select a contribution.')

    await page.getByRole('button', { name: 'Clear filters' }).click()
    await expect(
      page.getByRole('button', { name: /Login button breaks on mobile Safari/i }),
    ).toBeVisible()
  })

  await test.step('open a contribution detail and submit maintainer feedback', async () => {
    await page.getByRole('button', { name: /Throttle webhook replay retries/i }).click()

    const detailCard = page.locator('.detail-card')
    await expect(detailCard).toContainText('Throttle webhook replay retries')
    await expect(detailCard).toContainText(
      'Adds a small backoff around webhook replay fetches so transient 502s do not fan out into duplicate processing.',
    )

    await page.getByLabel('Correct labels').fill('maintainerki:worth-a-look,backend')
    await page.getByLabel('Notes').fill('Looks accurate. Good retry shape and clear scope.')
    await page.getByRole('button', { name: 'Good score' }).click()

    await expect(page.locator('.feedback-history')).toContainText(
      'Looks accurate. Good retry shape and clear scope.',
    )
    await expect(page.locator('.feedback-history')).toContainText('agreed')
  })

  await test.step('log out back to the admin gate', async () => {
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page.getByRole('heading', { name: 'Maintainer sign-in' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Maintainer inbox dashboard' })).toHaveCount(0)
  })
})

import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dashboardRoot = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dashboardRoot, '..')
const pythonBin = process.env.PW_PYTHON ?? path.join(repoRoot, '.venv', 'bin', 'python')
const e2eDbPath = path.join(dashboardRoot, 'e2e', '.tmp', 'maintainerki.e2e.sqlite')

const inheritedEnv = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
)

const backendEnv = {
  ...inheritedEnv,
  APP_ENV: 'test',
  DATABASE_URL: `sqlite:///${e2eDbPath}`,
  MAINTAINERKI_E2E_DB_PATH: e2eDbPath,
  ADMIN_AUTH_ENABLED: 'true',
  ADMIN_USERNAME: 'admin',
  ADMIN_PASSWORD: 'let-me-in',
  SESSION_SECRET: 'maintainerki-playwright-session-secret-1234567890',
  SESSION_COOKIE_SECURE: 'false',
  TRUSTED_HOSTS: '127.0.0.1,localhost',
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  outputDir: './e2e/.artifacts/test-results',
  reporter: [
    [process.env.CI ? 'dot' : 'list'],
    ['html', { open: 'never', outputFolder: './e2e/.artifacts/playwright-report' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${pythonBin}" dashboard/e2e/seed_backend.py && "${pythonBin}" -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --log-level warning`,
      cwd: repoRoot,
      env: backendEnv,
      url: 'http://127.0.0.1:8000/healthz',
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 3000',
      cwd: dashboardRoot,
      env: inheritedEnv,
      url: 'http://127.0.0.1:3000',
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
      timeout: 120_000,
    },
  ],
})

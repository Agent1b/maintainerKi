import axios from 'axios'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import './App.css'
import { ContributionDetail } from './components/ContributionDetail'
import { ContributionList } from './components/ContributionList'
import { InboxFilters } from './components/InboxFilters'
import { RepositorySidebar } from './components/RepositorySidebar'
import { StatsPanel } from './components/StatsPanel'
import {
  fetchAuthSession,
  fetchContributionDetail,
  fetchInbox,
  fetchRepoStats,
  fetchRepositories,
  login,
  logout,
  submitFeedback,
  type InboxFilters as InboxFiltersType,
} from './lib/api'
import type {
  AuthSession,
  ContributionDetail as ContributionDetailType,
  ContributionSummary,
  RepoStats,
  RepositorySummary,
} from './types'

function App() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [loginUsername, setLoginUsername] = useState('admin')
  const [loginPassword, setLoginPassword] = useState('')
  const [submittingLogin, setSubmittingLogin] = useState(false)
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [selectedRepoId, setSelectedRepoId] = useState<number | null>(null)
  const [filters, setFilters] = useState<InboxFiltersType>({})
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [inbox, setInbox] = useState<ContributionSummary[]>([])
  const [selectedContributionId, setSelectedContributionId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ContributionDetailType | null>(null)
  const [stats, setStats] = useState<RepoStats | null>(null)
  const [loadingRepositories, setLoadingRepositories] = useState(false)
  const [loadingInbox, setLoadingInbox] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingStats, setLoadingStats] = useState(false)
  const [submittingFeedback, setSubmittingFeedback] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reposRequestRef = useRef(0)
  const inboxRequestRef = useRef(0)
  const detailRequestRef = useRef(0)
  const statsRequestRef = useRef(0)
  const selectedContributionIdRef = useRef<number | null>(null)

  function setSelectedContribution(contributionId: number | null) {
    selectedContributionIdRef.current = contributionId
    setSelectedContributionId(contributionId)
  }

  useEffect(() => {
    void initializeApp()
  }, [])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedSearch(filters.search ?? '')
    }, 300)
    return () => window.clearTimeout(handle)
  }, [filters.search])

  const { status, kind, minScore, duplicatesOnly, suspiciousOnly } = filters

  const inboxFilters = useMemo(
    () => ({
      status,
      kind,
      minScore,
      duplicatesOnly,
      suspiciousOnly,
      search: debouncedSearch || undefined,
    }),
    [status, kind, minScore, duplicatesOnly, suspiciousOnly, debouncedSearch],
  )

  useEffect(() => {
    if (selectedRepoId === null) {
      setInbox([])
      setStats(null)
      setSelectedContribution(null)
      setDetail(null)
      return
    }

    void loadInbox(selectedRepoId, inboxFilters)
  }, [selectedRepoId, inboxFilters])

  useEffect(() => {
    if (selectedRepoId === null) {
      return
    }
    void loadStats(selectedRepoId)
  }, [selectedRepoId])

  useEffect(() => {
    if (selectedContributionId === null) {
      setDetail(null)
      return
    }
    void loadDetail(selectedContributionId)
  }, [selectedContributionId])

  const selectedRepo = useMemo(
    () => repositories.find((repo) => repo.id === selectedRepoId) ?? null,
    [repositories, selectedRepoId],
  )

  async function loadRepositories() {
    const token = ++reposRequestRef.current
    try {
      setLoadingRepositories(true)
      setError(null)
      const nextRepos = await fetchRepositories()
      if (reposRequestRef.current !== token) {
        return
      }
      setRepositories(nextRepos)
      setSelectedRepoId((current) => {
        if (current !== null && nextRepos.some((repo) => repo.id === current)) {
          return current
        }
        return nextRepos[0]?.id ?? null
      })
    } catch (caughtError) {
      if (reposRequestRef.current !== token) {
        return
      }
      if (handleUnauthorized(caughtError)) {
        return
      }
      setError(getErrorMessage(caughtError))
    } finally {
      if (reposRequestRef.current === token) {
        setLoadingRepositories(false)
      }
    }
  }

  async function loadInbox(repoId: number, nextFilters: InboxFiltersType) {
    const token = ++inboxRequestRef.current
    try {
      setLoadingInbox(true)
      setError(null)
      const items = await fetchInbox(repoId, nextFilters)
      if (inboxRequestRef.current !== token) {
        return
      }
      setInbox(items)
      const current = selectedContributionIdRef.current
      const nextSelected =
        current !== null && items.some((item) => item.id === current)
          ? current
          : (items[0]?.id ?? null)
      setSelectedContribution(nextSelected)
    } catch (caughtError) {
      if (inboxRequestRef.current !== token) {
        return
      }
      if (handleUnauthorized(caughtError)) {
        return
      }
      setError(getErrorMessage(caughtError))
    } finally {
      if (inboxRequestRef.current === token) {
        setLoadingInbox(false)
      }
    }
  }

  async function loadDetail(contributionId: number) {
    const token = ++detailRequestRef.current
    try {
      setLoadingDetail(true)
      setError(null)
      const nextDetail = await fetchContributionDetail(contributionId)
      if (detailRequestRef.current !== token) {
        return
      }
      setDetail(nextDetail)
    } catch (caughtError) {
      if (detailRequestRef.current !== token) {
        return
      }
      if (handleUnauthorized(caughtError)) {
        return
      }
      setError(getErrorMessage(caughtError))
    } finally {
      if (detailRequestRef.current === token) {
        setLoadingDetail(false)
      }
    }
  }

  async function loadStats(repoId: number) {
    const token = ++statsRequestRef.current
    try {
      setLoadingStats(true)
      const nextStats = await fetchRepoStats(repoId)
      if (statsRequestRef.current !== token) {
        return
      }
      setStats(nextStats)
    } catch (caughtError) {
      if (statsRequestRef.current !== token) {
        return
      }
      if (handleUnauthorized(caughtError)) {
        return
      }
      setError(getErrorMessage(caughtError))
    } finally {
      if (statsRequestRef.current === token) {
        setLoadingStats(false)
      }
    }
  }

  async function handleSubmitFeedback(payload: {
    maintainer_action: 'agreed' | 'disagreed' | 'override'
    correct_labels: string[]
    notes: string | null
  }) {
    if (detail === null) {
      return
    }

    const contributionId = detail.id

    try {
      setSubmittingFeedback(true)
      setError(null)
      const nextDetail = await submitFeedback(contributionId, payload)
      if (selectedContributionIdRef.current === contributionId) {
        setDetail(nextDetail)
      }
      if (selectedRepoId !== null) {
        await Promise.all([loadInbox(selectedRepoId, inboxFilters), loadStats(selectedRepoId)])
      }
    } catch (caughtError) {
      if (handleUnauthorized(caughtError)) {
        return
      }
      setError(getErrorMessage(caughtError))
    } finally {
      setSubmittingFeedback(false)
    }
  }

  async function handleRefresh() {
    const tasks: Promise<void>[] = [loadRepositories()]
    if (selectedRepoId !== null) {
      tasks.push(loadInbox(selectedRepoId, inboxFilters), loadStats(selectedRepoId))
    }
    if (selectedContributionId !== null) {
      tasks.push(loadDetail(selectedContributionId))
    }
    await Promise.all(tasks)
  }

  async function initializeApp() {
    try {
      setAuthLoading(true)
      setError(null)
      const nextSession = await fetchAuthSession()
      setAuthSession(nextSession)
      if (nextSession.username) {
        setLoginUsername(nextSession.username)
      }
      if (!nextSession.auth_enabled || nextSession.authenticated) {
        await loadRepositories()
      } else {
        resetWorkspace()
      }
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setAuthLoading(false)
    }
  }

  async function handleLoginSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      setSubmittingLogin(true)
      setError(null)
      await login(loginUsername, loginPassword)
      setLoginPassword('')
      await initializeApp()
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setSubmittingLogin(false)
    }
  }

  async function handleLogout() {
    try {
      setError(null)
      await logout()
    } finally {
      setAuthSession({
        auth_enabled: true,
        authenticated: false,
        username: null,
      })
      setLoginPassword('')
      resetWorkspace()
    }
  }

  function handleUnauthorized(caughtError: unknown): boolean {
    if (!axios.isAxiosError(caughtError) || caughtError.response?.status !== 401) {
      return false
    }
    setAuthSession({
      auth_enabled: true,
      authenticated: false,
      username: null,
    })
    setLoginPassword('')
    resetWorkspace()
    setError('Your session expired. Sign in again to continue.')
    return true
  }

  function resetWorkspace() {
    setRepositories([])
    setSelectedRepoId(null)
    setInbox([])
    setSelectedContribution(null)
    setDetail(null)
    setStats(null)
  }

  if (authLoading) {
    return (
      <div className="app-shell auth-shell">
        <section className="card auth-card">
          <span className="eyebrow">maintainerKi</span>
          <h1>Checking dashboard access…</h1>
          <p className="muted">Loading your session and workspace.</p>
        </section>
      </div>
    )
  }

  if (authSession?.auth_enabled && !authSession.authenticated) {
    return (
      <div className="app-shell auth-shell">
        <section className="card auth-card">
          <span className="eyebrow">maintainerKi</span>
          <h1>Maintainer sign-in</h1>
          <p className="muted">
            This dashboard is running in private admin mode. Sign in before loading repository
            data or writing labels back to GitHub.
          </p>

          <form className="auth-form" onSubmit={handleLoginSubmit}>
            <label>
              <span>Username</span>
              <input
                type="text"
                autoComplete="username"
                value={loginUsername}
                onChange={(event) => setLoginUsername(event.target.value)}
                required
              />
            </label>

            <label>
              <span>Password</span>
              <input
                type="password"
                autoComplete="current-password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                required
              />
            </label>

            <button type="submit" className="primary-button" disabled={submittingLogin}>
              {submittingLogin ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {error ? <div className="error-banner">{error}</div> : null}
        </section>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <span className="eyebrow">maintainerKi</span>
          <h1>Maintainer inbox dashboard</h1>
          <p>
            Triage GitHub issues and pull requests with scores, duplicate hints, and maintainer
            feedback in one place.
          </p>
        </div>
        <div className="header-actions">
          {authSession?.auth_enabled ? (
            <span className="muted auth-note">Signed in as {authSession.username ?? 'admin'}</span>
          ) : null}
          <button type="button" className="secondary-button" onClick={() => void handleRefresh()}>
            Refresh
          </button>
          {authSession?.auth_enabled ? (
            <button type="button" className="secondary-button" onClick={() => void handleLogout()}>
              Sign out
            </button>
          ) : null}
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <main className="layout">
        <RepositorySidebar
          repositories={repositories}
          selectedRepoId={selectedRepoId}
          onSelect={setSelectedRepoId}
        />

        <div className="main-column">
          <StatsPanel
            repository={selectedRepo}
            stats={stats}
            loading={loadingRepositories || loadingStats}
          />

          <InboxFilters value={filters} onChange={setFilters} />

          <div className="workspace-grid">
            <ContributionList
              items={inbox}
              loading={loadingRepositories || loadingInbox}
              selectedContributionId={selectedContributionId}
              onSelect={setSelectedContribution}
            />

            <ContributionDetail
              detail={detail}
              loading={loadingDetail}
              onSubmitFeedback={handleSubmitFeedback}
              submittingFeedback={submittingFeedback}
            />
          </div>
        </div>
      </main>
    </div>
  )
}

function getErrorMessage(caughtError: unknown): string {
  if (axios.isAxiosError(caughtError)) {
    if (typeof caughtError.response?.data?.detail === 'string') {
      return caughtError.response.data.detail
    }
    if (caughtError.response?.status === 401) {
      return 'Authentication required.'
    }
  }
  if (caughtError instanceof Error) {
    return caughtError.message
  }
  return 'Something went wrong while talking to the dashboard API.'
}

export default App

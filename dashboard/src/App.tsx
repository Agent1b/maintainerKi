import { useEffect, useMemo, useState } from 'react'
import './App.css'
import { ContributionDetail } from './components/ContributionDetail'
import { ContributionList } from './components/ContributionList'
import { InboxFilters } from './components/InboxFilters'
import { RepositorySidebar } from './components/RepositorySidebar'
import { StatsPanel } from './components/StatsPanel'
import {
  fetchContributionDetail,
  fetchInbox,
  fetchRepoStats,
  fetchRepositories,
  submitFeedback,
  type InboxFilters as InboxFiltersType,
} from './lib/api'
import type {
  ContributionDetail as ContributionDetailType,
  ContributionSummary,
  RepoStats,
  RepositorySummary,
} from './types'

function App() {
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [selectedRepoId, setSelectedRepoId] = useState<number | null>(null)
  const [filters, setFilters] = useState<InboxFiltersType>({})
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [inbox, setInbox] = useState<ContributionSummary[]>([])
  const [selectedContributionId, setSelectedContributionId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ContributionDetailType | null>(null)
  const [stats, setStats] = useState<RepoStats | null>(null)
  const [loadingRepositories, setLoadingRepositories] = useState(true)
  const [loadingInbox, setLoadingInbox] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingStats, setLoadingStats] = useState(false)
  const [submittingFeedback, setSubmittingFeedback] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadRepositories()
  }, [])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedSearch(filters.search ?? '')
    }, 300)
    return () => window.clearTimeout(handle)
  }, [filters.search])

  const inboxFilters = useMemo(
    () => ({
      ...filters,
      search: debouncedSearch || undefined,
    }),
    [debouncedSearch, filters],
  )

  useEffect(() => {
    if (selectedRepoId === null) {
      setInbox([])
      setStats(null)
      setSelectedContributionId(null)
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
    try {
      setLoadingRepositories(true)
      setError(null)
      const nextRepos = await fetchRepositories()
      setRepositories(nextRepos)
      setSelectedRepoId((current) => current ?? nextRepos[0]?.id ?? null)
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setLoadingRepositories(false)
    }
  }

  async function loadInbox(repoId: number, nextFilters: InboxFiltersType) {
    try {
      setLoadingInbox(true)
      setError(null)
      const items = await fetchInbox(repoId, nextFilters)
      setInbox(items)
      setSelectedContributionId((current) => {
        if (current && items.some((item) => item.id === current)) {
          return current
        }
        return items[0]?.id ?? null
      })
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setLoadingInbox(false)
    }
  }

  async function loadDetail(contributionId: number) {
    try {
      setLoadingDetail(true)
      setError(null)
      const nextDetail = await fetchContributionDetail(contributionId)
      setDetail(nextDetail)
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setLoadingDetail(false)
    }
  }

  async function loadStats(repoId: number) {
    try {
      setLoadingStats(true)
      const nextStats = await fetchRepoStats(repoId)
      setStats(nextStats)
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setLoadingStats(false)
    }
  }

  async function handleSubmitFeedback(payload: {
    maintainer_action: 'agreed' | 'disagreed' | 'override'
    correct_labels: string[]
    notes: string | null
  }) {
    if (selectedContributionId === null) {
      return
    }

    try {
      setSubmittingFeedback(true)
      setError(null)
      const nextDetail = await submitFeedback(selectedContributionId, payload)
      setDetail(nextDetail)
      if (selectedRepoId !== null) {
        await Promise.all([loadInbox(selectedRepoId, inboxFilters), loadStats(selectedRepoId)])
      }
    } catch (caughtError) {
      setError(getErrorMessage(caughtError))
    } finally {
      setSubmittingFeedback(false)
    }
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
        <button type="button" className="secondary-button" onClick={() => void loadRepositories()}>
          Refresh
        </button>
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
              onSelect={setSelectedContributionId}
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
  if (caughtError instanceof Error) {
    return caughtError.message
  }
  return 'Something went wrong while talking to the dashboard API.'
}

export default App

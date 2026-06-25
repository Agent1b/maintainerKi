import { lazy, Suspense } from 'react'
import { formatDistanceToNowStrict } from 'date-fns'
import type { RepoStats, RepositorySummary } from '../types'

const StatsCharts = lazy(() =>
  import('./StatsCharts').then((module) => ({
    default: module.StatsCharts,
  })),
)

type StatsPanelProps = {
  repository: RepositorySummary | null
  stats: RepoStats | null
  loading: boolean
}

export function StatsPanel({ repository, stats, loading }: StatsPanelProps) {
  const distributionData = stats
    ? [
        { bucket: 'High', value: stats.score_distribution.high },
        { bucket: 'Medium', value: stats.score_distribution.medium },
        { bucket: 'Low', value: stats.score_distribution.low },
      ]
    : []

  return (
    <section className="card stats-card">
      <div className="section-header">
        <div>
          <h2>Dashboard overview</h2>
          <p className="muted">
            {repository
              ? `Tracking ${repository.name}${
                  repository.last_received_at
                    ? ` · last event ${formatDistanceToNowStrict(
                        new Date(repository.last_received_at),
                        { addSuffix: true },
                      )}`
                    : ''
                }`
              : 'Select a repository to see stats'}
          </p>
        </div>
      </div>

      {loading ? (
        <div className="empty-state">
          <p>Loading stats…</p>
        </div>
      ) : !stats ? (
        <div className="empty-state">
          <p>No stats yet.</p>
        </div>
      ) : (
        <>
          <div className="stats-grid">
            <div className="stat-tile">
              <span className="stat-label">Queue depth</span>
              <strong>{stats.queue_depth}</strong>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Reviewed</span>
              <strong>{stats.reviewed_count}</strong>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Suspicious</span>
              <strong>{stats.suspicious_count}</strong>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Duplicates</span>
              <strong>{stats.duplicate_count}</strong>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Avg processing</span>
              <strong>
                {stats.average_processing_latency_seconds !== null
                  ? `${stats.average_processing_latency_seconds}s`
                  : '—'}
              </strong>
            </div>
          </div>

          <div className="charts-grid">
            <Suspense
              fallback={
                <>
                  <div className="chart-panel chart-loading">
                    <h3>Score distribution</h3>
                    <p className="muted">Loading chart…</p>
                  </div>
                  <div className="chart-panel chart-loading">
                    <h3>Activity timeline</h3>
                    <p className="muted">Loading chart…</p>
                  </div>
                </>
              }
            >
              <StatsCharts
                activityTimeline={stats.activity_timeline}
                distributionData={distributionData}
              />
            </Suspense>
          </div>
        </>
      )}
    </section>
  )
}

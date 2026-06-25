import { formatDistanceToNowStrict } from 'date-fns'
import type { RepositorySummary } from '../types'

type RepositorySidebarProps = {
  repositories: RepositorySummary[]
  selectedRepoId: number | null
  onSelect: (repoId: number) => void
}

export function RepositorySidebar({
  repositories,
  selectedRepoId,
  onSelect,
}: RepositorySidebarProps) {
  return (
    <aside className="sidebar card">
      <div className="section-header">
        <h2>Repositories</h2>
        <span className="muted">{repositories.length}</span>
      </div>

      {repositories.length === 0 ? (
        <div className="empty-state">
          <p>No repositories yet.</p>
          <span className="muted">Once webhooks land, they will show up here.</span>
        </div>
      ) : (
        <div className="repo-list">
          {repositories.map((repo) => {
            const isActive = repo.id === selectedRepoId
            return (
              <button
                key={repo.id}
                type="button"
                className={`repo-button ${isActive ? 'active' : ''}`}
                onClick={() => onSelect(repo.id)}
              >
                <div className="repo-button-top">
                  <strong>{repo.name}</strong>
                  <span className="badge neutral">{repo.contribution_count}</span>
                </div>
                <div className="repo-metrics">
                  <span>Scored {repo.scored_count}</span>
                  <span>Dupes {repo.duplicate_count}</span>
                  <span>Suspicious {repo.suspicious_count}</span>
                </div>
                <div className="repo-footer muted">
                  {repo.last_received_at
                    ? `Last event ${formatDistanceToNowStrict(new Date(repo.last_received_at), {
                        addSuffix: true,
                      })}`
                    : 'No activity yet'}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </aside>
  )
}

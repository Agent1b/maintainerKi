import { formatDistanceToNowStrict } from 'date-fns'
import type { ContributionSummary } from '../types'

type ContributionListProps = {
  items: ContributionSummary[]
  loading: boolean
  selectedContributionId: number | null
  onSelect: (contributionId: number) => void
}

const bucketTone: Record<string, string> = {
  pending: 'neutral',
  duplicate: 'purple',
  suspicious: 'danger',
  'review-first': 'success',
  'worth-a-look': 'warning',
  'low-priority': 'neutral',
}

export function ContributionList({
  items,
  loading,
  selectedContributionId,
  onSelect,
}: ContributionListProps) {
  return (
    <section className="card contribution-list-card">
      <div className="section-header">
        <h2>Inbox</h2>
        <span className="muted">{loading ? 'Loading…' : `${items.length} items`}</span>
      </div>

      {loading ? (
        <div className="empty-state">
          <p>Loading contributions…</p>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p>No matches.</p>
          <span className="muted">Try widening your filters or wait for more webhook events.</span>
        </div>
      ) : (
        <div className="contribution-list">
          {items.map((item) => {
            const isActive = item.id === selectedContributionId
            return (
              <button
                key={item.id}
                type="button"
                className={`contribution-row ${isActive ? 'active' : ''}`}
                onClick={() => onSelect(item.id)}
              >
                <div className="contribution-header">
                  <div>
                    <span className={`badge ${bucketTone[item.triage_bucket] ?? 'neutral'}`}>
                      {item.triage_bucket}
                    </span>
                    <span className="issue-ref">
                      {item.kind === 'pull_request' ? 'PR' : 'Issue'} #{item.number}
                    </span>
                  </div>
                  <span className="score-pill">
                    {item.overall_score ?? '—'}
                  </span>
                </div>

                <strong className="contribution-title">{item.title}</strong>
                <p className="contribution-summary">{item.summary ?? 'No summary yet.'}</p>

                <div className="label-row">
                  {item.labels.slice(0, 4).map((label) => (
                    <span key={label} className="mini-label">
                      {label}
                    </span>
                  ))}
                </div>

                <div className="contribution-meta muted">
                  <span>{item.author ?? 'unknown author'}</span>
                  <span>
                    {item.received_at
                      ? formatDistanceToNowStrict(new Date(item.received_at), { addSuffix: true })
                      : 'unknown time'}
                  </span>
                  {item.possible_duplicate ? <span>possible duplicate</span> : null}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

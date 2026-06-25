import { formatDistanceToNowStrict } from 'date-fns'
import { useEffect, useMemo, useState } from 'react'
import type { ContributionDetail, FeedbackPayload } from '../types'

type ContributionDetailProps = {
  detail: ContributionDetail | null
  loading: boolean
  onSubmitFeedback: (payload: FeedbackPayload) => Promise<void>
  submittingFeedback: boolean
}

export function ContributionDetail({
  detail,
  loading,
  onSubmitFeedback,
  submittingFeedback,
}: ContributionDetailProps) {
  const [notes, setNotes] = useState('')
  const [correctLabelsInput, setCorrectLabelsInput] = useState('')

  useEffect(() => {
    setNotes('')
    setCorrectLabelsInput(detail?.score.suggested_labels.join(', ') ?? '')
  }, [detail?.id, detail?.score.suggested_labels])

  const parsedLabels = useMemo(
    () =>
      correctLabelsInput
        .split(',')
        .map((label) => label.trim())
        .filter(Boolean),
    [correctLabelsInput],
  )

  if (loading) {
    return (
      <section className="card detail-card">
        <div className="empty-state">
          <p>Loading details…</p>
        </div>
      </section>
    )
  }

  if (!detail) {
    return (
      <section className="card detail-card">
        <div className="empty-state">
          <p>Select a contribution.</p>
          <span className="muted">The detail pane will open here.</span>
        </div>
      </section>
    )
  }

  return (
    <section className="card detail-card">
      <div className="detail-header">
        <div>
          <div className="detail-kicker">
            {detail.kind === 'pull_request' ? 'Pull request' : 'Issue'} #{detail.number}
          </div>
          <h2>{detail.title}</h2>
          <div className="detail-meta muted">
            <span>{detail.author ?? 'unknown author'}</span>
            <span>{detail.status}</span>
            <span>
              {detail.received_at
                ? formatDistanceToNowStrict(new Date(detail.received_at), { addSuffix: true })
                : 'unknown time'}
            </span>
          </div>
        </div>
        {detail.html_url ? (
          <a className="primary-link" href={detail.html_url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        ) : null}
      </div>

      <div className="score-grid">
        <ScoreCard label="Overall" value={detail.score.overall_score} tone="primary" />
        <ScoreCard label="Quality" value={detail.score.quality} />
        <ScoreCard label="Relevance" value={detail.score.relevance} />
        <ScoreCard label="Completeness" value={detail.score.completeness} />
        <ScoreCard label="Suspicion" value={detail.score.suspicion} tone="danger" />
      </div>

      <div className="detail-section">
        <h3>AI summary</h3>
        <p>{detail.score.summary ?? 'No summary yet.'}</p>
      </div>

      <div className="detail-section">
        <h3>Suggested labels</h3>
        {detail.score.has_maintainer_label_override ? (
          <p className="muted">Showing the maintainer override labels currently stored for this item.</p>
        ) : null}
        <div className="label-row">
          {detail.score.suggested_labels.map((label) => (
            <span key={label} className="mini-label">
              {label}
            </span>
          ))}
        </div>
        {detail.score.has_maintainer_label_override && detail.score.ai_suggested_labels?.length ? (
          <>
            <h4 className="muted">Original AI labels</h4>
            <div className="label-row">
              {detail.score.ai_suggested_labels.map((label) => (
                <span key={label} className="mini-label">
                  {label}
                </span>
              ))}
            </div>
          </>
        ) : null}
      </div>

      <div className="detail-section">
        <h3>Contribution body</h3>
        <pre className="body-preview">{detail.body || 'No body provided.'}</pre>
      </div>

      <div className="detail-section">
        <h3>Duplicate candidates</h3>
        {detail.duplicates.candidates.length === 0 ? (
          <p className="muted">No duplicate candidates were found.</p>
        ) : (
          <div className="duplicate-list">
            {detail.duplicates.candidates.map((candidate) => (
              <a
                key={`${candidate.contribution_id}-${candidate.number}`}
                className="duplicate-item"
                href={candidate.html_url ?? '#'}
                target="_blank"
                rel="noreferrer"
              >
                <div>
                  <strong>
                    #{candidate.number} · {candidate.title}
                  </strong>
                  <div className="muted">{candidate.kind}</div>
                </div>
                <span className="badge purple">
                  {Math.round(candidate.similarity * 100)}% similar
                </span>
              </a>
            ))}
          </div>
        )}
      </div>

      <div className="detail-section">
        <h3>Maintainer feedback</h3>
        <div className="feedback-form">
          <label>
            <span>Correct labels</span>
            <input
              type="text"
              value={correctLabelsInput}
              onChange={(event) => setCorrectLabelsInput(event.target.value)}
              placeholder="comma,separated,labels"
            />
          </label>

          <label>
            <span>Notes</span>
            <textarea
              rows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="What felt right or wrong?"
            />
          </label>

          <div className="feedback-actions">
            <button
              type="button"
              className="primary-button"
              disabled={submittingFeedback}
              onClick={() =>
                onSubmitFeedback({
                  maintainer_action: 'agreed',
                  correct_labels: parsedLabels,
                  notes: notes || null,
                })
              }
            >
              Good score
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={submittingFeedback}
              onClick={() =>
                onSubmitFeedback({
                  maintainer_action: 'disagreed',
                  correct_labels: parsedLabels,
                  notes: notes || null,
                })
              }
            >
              Wrong score
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={submittingFeedback}
              onClick={() =>
                onSubmitFeedback({
                  maintainer_action: 'override',
                  correct_labels: parsedLabels,
                  notes: notes || null,
                })
              }
            >
              Save label override
            </button>
          </div>
        </div>

        <div className="feedback-history">
          {detail.feedback.length === 0 ? (
            <p className="muted">No maintainer feedback yet.</p>
          ) : (
            detail.feedback.map((entry) => (
              <div key={entry.id} className="feedback-entry">
                <div className="feedback-entry-top">
                  <strong>{entry.maintainer_action}</strong>
                  <span className="muted">
                    {entry.created_at
                      ? formatDistanceToNowStrict(new Date(entry.created_at), {
                          addSuffix: true,
                        })
                      : 'unknown'}
                  </span>
                </div>
                {entry.correct_labels.length > 0 ? (
                  <div className="label-row">
                    {entry.correct_labels.map((label) => (
                      <span key={label} className="mini-label">
                        {label}
                      </span>
                    ))}
                  </div>
                ) : null}
                {entry.notes ? <p>{entry.notes}</p> : null}
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  )
}

type ScoreCardProps = {
  label: string
  value: number | null
  tone?: 'primary' | 'danger'
}

function ScoreCard({ label, value, tone = 'primary' }: ScoreCardProps) {
  return (
    <div className={`score-card ${tone}`}>
      <span className="score-card-label">{label}</span>
      <strong>{value ?? '—'}</strong>
    </div>
  )
}

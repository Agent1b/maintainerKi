import type { InboxFilters as InboxFiltersType } from '../lib/api'

type InboxFiltersProps = {
  value: InboxFiltersType
  onChange: (next: InboxFiltersType) => void
}

export function InboxFilters({ value, onChange }: InboxFiltersProps) {
  return (
    <div className="filters card">
      <div className="section-header">
        <h2>Inbox filters</h2>
      </div>

      <div className="filter-grid">
        <label>
          <span>Status</span>
          <select
            value={value.status ?? ''}
            onChange={(event) =>
              onChange({
                ...value,
                status: event.target.value || undefined,
              })
            }
          >
            <option value="">All</option>
            <option value="scored">Scored</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
          </select>
        </label>

        <label>
          <span>Type</span>
          <select
            value={value.kind ?? ''}
            onChange={(event) =>
              onChange({
                ...value,
                kind: (event.target.value as 'issue' | 'pull_request' | '') || '',
              })
            }
          >
            <option value="">All</option>
            <option value="issue">Issues</option>
            <option value="pull_request">Pull requests</option>
          </select>
        </label>

        <label>
          <span>Min score</span>
          <input
            type="number"
            min={0}
            max={100}
            value={value.minScore ?? ''}
            onChange={(event) =>
              onChange({
                ...value,
                minScore:
                  event.target.value === '' ? undefined : Number.parseInt(event.target.value, 10),
              })
            }
          />
        </label>

        <label className="search-filter">
          <span>Search</span>
          <input
            type="search"
            placeholder="Title, author, body..."
            value={value.search ?? ''}
            onChange={(event) =>
              onChange({
                ...value,
                search: event.target.value || undefined,
              })
            }
          />
        </label>
      </div>

      <div className="toggle-row">
        <label className="toggle">
          <input
            type="checkbox"
            checked={Boolean(value.duplicatesOnly)}
            onChange={(event) =>
              onChange({
                ...value,
                duplicatesOnly: event.target.checked,
              })
            }
          />
          <span>Duplicates only</span>
        </label>

        <label className="toggle">
          <input
            type="checkbox"
            checked={Boolean(value.suspiciousOnly)}
            onChange={(event) =>
              onChange({
                ...value,
                suspiciousOnly: event.target.checked,
              })
            }
          />
          <span>Suspicious only</span>
        </label>

        <button
          type="button"
          className="secondary-button"
          onClick={() => onChange({})}
        >
          Clear filters
        </button>
      </div>
    </div>
  )
}

export type RepositorySummary = {
  id: number
  name: string
  contribution_count: number
  scored_count: number
  duplicate_count: number
  suspicious_count: number
  pending_count?: number
  last_received_at: string | null
}

export type ContributionSummary = {
  id: number
  repository_id: number | null
  repository: string
  kind: 'issue' | 'pull_request'
  number: number
  title: string
  author: string | null
  status: string
  overall_score: number | null
  suspicion_score: number | null
  possible_duplicate: boolean
  labels: string[]
  summary: string | null
  html_url: string | null
  received_at: string | null
  scored_at: string | null
  triage_bucket: string
}

export type DuplicateCandidate = {
  contribution_id: number
  repository: string
  kind: string
  number: number
  title: string
  html_url: string | null
  similarity: number
}

export type ContributionDetail = {
  id: number
  repository_id: number | null
  repository: string
  github_id: number | null
  kind: 'issue' | 'pull_request'
  action: string
  number: number
  title: string
  body: string
  author: string | null
  sender: string | null
  status: string
  html_url: string | null
  score: {
    quality: number | null
    relevance: number | null
    completeness: number | null
    suspicion: number | null
    overall_score: number | null
    summary: string | null
    suggested_labels: string[]
    ai_suggested_labels?: string[]
    maintainer_override_labels?: string[]
    has_maintainer_label_override?: boolean
    provider: string | null
    model: string | null
    prompt_version: string | null
  }
  duplicates: {
    possible_duplicate: boolean
    top_similarity: number | null
    embedding_provider: string | null
    embedding_model: string | null
    candidates: DuplicateCandidate[]
    checked_at: string | null
  }
  error: string | null
  received_at: string | null
  scored_at: string | null
  updated_at: string | null
  feedback: FeedbackEntry[]
}

export type FeedbackEntry = {
  id: number
  contribution_id: number
  maintainer_action: 'agreed' | 'disagreed' | 'override'
  correct_labels: string[]
  notes: string | null
  created_at: string | null
}

export type RepoStats = {
  repository: RepositorySummary
  queue_depth: number
  reviewed_count: number
  suspicious_count: number
  duplicate_count: number
  average_processing_latency_seconds: number | null
  score_distribution: {
    high: number
    medium: number
    low: number
  }
  activity_timeline: Array<{
    date: string
    count: number
  }>
}

export type FeedbackPayload = {
  maintainer_action: 'agreed' | 'disagreed' | 'override'
  correct_labels: string[]
  notes: string | null
}

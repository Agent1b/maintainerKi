import axios from 'axios'
import type {
  ContributionDetail,
  ContributionSummary,
  FeedbackPayload,
  RepoStats,
  RepositorySummary,
} from '../types'

const api = axios.create({
  baseURL: '/api',
})

export type InboxFilters = {
  status?: string
  kind?: 'issue' | 'pull_request' | ''
  minScore?: number
  duplicatesOnly?: boolean
  suspiciousOnly?: boolean
  search?: string
}

export async function fetchRepositories(): Promise<RepositorySummary[]> {
  const response = await api.get<{ repositories: RepositorySummary[] }>('/repos')
  return response.data.repositories
}

export async function fetchInbox(
  repoId: number,
  filters: InboxFilters,
): Promise<ContributionSummary[]> {
  const response = await api.get<{ items: ContributionSummary[] }>(`/repos/${repoId}/inbox`, {
    params: {
      status: filters.status || undefined,
      kind: filters.kind || undefined,
      min_score: filters.minScore ?? undefined,
      duplicates_only: filters.duplicatesOnly || undefined,
      suspicious_only: filters.suspiciousOnly || undefined,
      search: filters.search || undefined,
    },
  })
  return response.data.items
}

export async function fetchContributionDetail(
  contributionId: number,
): Promise<ContributionDetail> {
  const response = await api.get<ContributionDetail>(`/contributions/${contributionId}`)
  return response.data
}

export async function fetchRepoStats(repoId: number): Promise<RepoStats> {
  const response = await api.get<RepoStats>(`/repos/${repoId}/stats`)
  return response.data
}

export async function submitFeedback(
  contributionId: number,
  payload: FeedbackPayload,
): Promise<ContributionDetail> {
  const response = await api.post<{ contribution: ContributionDetail }>(
    `/contributions/${contributionId}/feedback`,
    payload,
  )
  return response.data.contribution
}

# maintainerKi Production MVP Checklist

This checklist turns the README vision into a production-minded MVP that is still small enough to ship.

---

## 1. Product Definition

### Core promise
- [ ] maintainerKi receives new GitHub issues and pull requests
- [ ] maintainerKi scores them for triage value
- [ ] maintainerKi flags likely duplicates or suspicious submissions
- [ ] maintainerKi suggests labels and priority
- [ ] maintainer always remains the final decision-maker

### MVP success criteria
- [ ] A maintainer installs the GitHub App on one or more repos
- [ ] New issues and PRs appear in maintainerKi within a few minutes
- [ ] Each contribution gets an analysis record with score, summary, and suggested labels
- [ ] The maintainer can open a dashboard and work a sorted inbox
- [ ] False positives are visible and easy to override
- [ ] Basic observability exists so production failures are discoverable

### Explicit non-goals for MVP
- [ ] No auto-closing of issues or PRs
- [ ] No auto-merging
- [ ] No fully autonomous moderation
- [ ] No marketplace-scale multi-tenant billing in MVP
- [ ] No advanced learning loop that retrains custom models

---

## 2. MVP Scope Lock

### P0: must ship
- [ ] GitHub App registration flow documented
- [ ] Webhook receiver with signature verification
- [ ] Background job queue for async processing
- [ ] Persistence layer for repositories and contributions
- [ ] AI scoring for quality / relevance / completeness / suspicion
- [ ] Suggested labels written back to GitHub
- [ ] Duplicate detection for issues and PRs
- [ ] Dashboard inbox with filters and detail view
- [ ] Maintainer feedback action for “good score” / “wrong score”
- [x] Basic production deployment path

### P1: valuable but can slip
- [ ] Queue and throughput charts
- [ ] Contributor profile summaries
- [ ] Repo-level custom thresholds
- [ ] AI explanation comment posted back to GitHub
- [ ] Bulk triage actions in dashboard

### Later
- [ ] GitHub Marketplace packaging
- [ ] Team roles / permissions
- [ ] Multi-org analytics
- [ ] Fine-tuned project-specific scoring
- [ ] Slack / Discord notifications

---

## 3. Repository and Developer Experience

- [x] Create backend directory structure
- [ ] Create dashboard directory structure
- [x] Add `.gitignore`
- [x] Add `.env.example`
- [x] Add `requirements.txt`
- [x] Add `docker-compose.yml`
- [x] Add `Makefile` or task runner commands
- [ ] Add project README at repo root when codebase becomes canonical
- [ ] Add linting and formatting tools
- [ ] Add pre-commit hooks

### Exit criteria
- [ ] A new developer can clone the repo, install dependencies, start services, and run tests from clean instructions

---

## 4. GitHub App and Webhook Intake

- [x] FastAPI app bootstrapped
- [x] `/healthz` endpoint exists
- [x] `/webhooks/github` endpoint exists
- [x] Verify `X-Hub-Signature-256` HMAC signature
- [x] Reject invalid signatures with correct status code
- [x] Accept and safely ignore unsupported events
- [x] Normalize incoming issue and PR payloads
- [x] Log useful metadata for ingest debugging
- [ ] Handle GitHub App installation events
- [ ] Store installation IDs and repo mappings
- [ ] Handle webhook delivery replay safely
- [ ] Add idempotency protection for duplicated deliveries

### Exit criteria
- [ ] A real GitHub webhook from a test repository reaches local dev and is accepted
- [ ] Invalid signatures are rejected
- [ ] Supported events are turned into queued jobs

---

## 5. Background Processing

- [ ] Add Celery worker
- [ ] Add Redis broker config
- [ ] Create “process contribution” task
- [ ] Pass only the minimal required payload to the worker
- [ ] Add retries with backoff for transient failures
- [ ] Mark permanent failures clearly
- [ ] Add dead-letter or failure logging strategy

### Exit criteria
- [ ] The API returns to GitHub quickly
- [ ] Processing still completes asynchronously even if scoring takes 30-60 seconds

---

## 6. Persistence and Data Model

### Core tables
- [ ] `repositories`
- [ ] `installations`
- [ ] `contributions`
- [ ] `duplicate_matches`
- [ ] `scoring_feedback`
- [ ] `webhook_deliveries`

### Contribution fields
- [ ] GitHub IDs and URLs
- [ ] repo link
- [ ] issue vs PR type
- [ ] title / body snapshot
- [ ] author identity data
- [ ] status lifecycle
- [ ] score breakdown
- [ ] AI summary
- [ ] suggested labels
- [ ] duplicate candidates
- [ ] timestamps

### Production data concerns
- [ ] Add Alembic migrations
- [ ] Define retention policy for raw payloads
- [ ] Decide whether to store diffs in full or summarized form
- [ ] Define indexing strategy for repo lookup, status, created time, score, and duplicate search

### Exit criteria
- [ ] A processed GitHub contribution becomes a queryable record in PostgreSQL

---

## 7. AI Scoring Engine

### Functional work
- [ ] Build LLM client abstraction
- [ ] Support at least one provider for MVP
- [ ] Add provider config via environment variables
- [ ] Create prompt template with strict JSON output
- [ ] Parse model response robustly
- [ ] Fail closed when model output is malformed
- [ ] Compute overall score from category scores
- [ ] Save raw score breakdown and one-sentence explanation

### Product quality work
- [ ] Define score semantics clearly
- [ ] Define suspicion scoring examples
- [ ] Define label mapping rules from score ranges
- [ ] Add prompt versioning
- [ ] Add evaluation fixtures with expected outputs

### Operational concerns
- [ ] Set timeout budget
- [ ] Add retry policy for provider/network failures
- [ ] Add fallback behavior when the model is unavailable
- [ ] Log token cost / request duration if using a paid provider

### Exit criteria
- [ ] A new issue or PR receives consistent structured scoring without blocking webhook response

---

## 8. Duplicate Detection

- [ ] Choose embedding provider for MVP
- [ ] Create title + body normalization rules
- [ ] Generate embeddings for contributions
- [ ] Store embeddings safely
- [ ] Compare against repo-local history only
- [ ] Return top N similar items with scores
- [ ] Set similarity threshold and document why
- [ ] Add dashboard display for duplicate candidates
- [ ] Add GitHub label for likely duplicates

### Scale path
- [ ] Use JSON vector storage first or adopt pgvector early
- [ ] Plan migration path if repo size grows

### Exit criteria
- [ ] Two semantically similar issues are surfaced as likely duplicates in the UI and labels

---

## 9. Labeling and GitHub Write-Back

- [ ] Authenticate as GitHub App installation
- [ ] Fetch installation token safely
- [ ] Create or apply maintainerKi labels
- [ ] Avoid clobbering human-applied labels
- [ ] Add optional GitHub comment with summary
- [ ] Record write-back result and failures
- [ ] Rate-limit outbound GitHub API calls

### Exit criteria
- [ ] After analysis, GitHub visibly shows the suggested triage labels

---

## 10. Dashboard MVP

### Inbox page
- [ ] Repo selector
- [ ] Sorted queue
- [ ] Filters by type, status, score, suspicion, duplicate
- [ ] Search by title / author / number
- [ ] Empty states
- [ ] Error states
- [ ] Loading states

### Detail page
- [ ] Full issue / PR metadata
- [ ] Score breakdown
- [ ] AI summary
- [ ] Suggested labels
- [ ] Duplicate candidates
- [ ] Direct link to GitHub
- [ ] Feedback controls

### MVP stats
- [ ] Queue depth
- [ ] Pending vs reviewed counts
- [ ] Average processing latency

### UX quality
- [ ] Keyboard navigation works
- [ ] Responsive layout works on laptop widths
- [ ] Contrast and focus states are visible

### Exit criteria
- [ ] A maintainer can triage their inbox from the dashboard without opening raw database records

---

## 11. Maintainer Feedback Loop

- [ ] Record “agreed” vs “wrong score”
- [ ] Record corrected labels
- [ ] Record duplicate confirmation or dismissal
- [ ] Show feedback state in dashboard
- [ ] Export feedback for later evaluation work

### Exit criteria
- [ ] Maintainers can tell the system when it got something wrong, and the signal is stored for later improvement

---

## 12. Security, Abuse, and Privacy

- [ ] Validate webhook signatures
- [ ] Keep secrets out of source control
- [ ] Add request size limits
- [ ] Add structured input validation
- [ ] Add rate limiting where appropriate
- [ ] Sanitize or escape any user-generated content rendered in dashboard
- [ ] Decide whether raw PR bodies and diffs are stored permanently
- [ ] Document PII handling and retention
- [ ] Minimize sensitive log contents
- [ ] Rotate GitHub credentials safely

### Exit criteria
- [ ] The app has a documented secrets strategy, basic abuse protections, and no obvious unsafe ingest path

---

## 13. Observability and Operations

- [ ] Structured application logs
- [ ] Request IDs / delivery IDs in logs
- [ ] Worker logs with job IDs
- [ ] Error reporting path
- [x] Health checks for API, DB, Redis, worker
- [ ] Uptime monitor
- [ ] Basic dashboard for queue failures or backlog growth

### Exit criteria
- [ ] When production breaks, you can tell whether the problem is webhook ingest, queue, model, DB, or GitHub write-back

---

## 14. Testing Strategy

### Unit tests
- [x] Webhook signature verification
- [x] Supported vs unsupported event behavior
- [ ] Score parsing
- [ ] Label mapping
- [ ] Duplicate similarity thresholds

### Integration tests
- [ ] Webhook -> queue -> DB flow
- [ ] Worker -> model client -> save result flow
- [ ] GitHub App token + label write-back
- [ ] Dashboard API endpoints

### End-to-end tests
- [ ] Test repo sends webhook
- [ ] Contribution appears in dashboard
- [ ] Labels show up on GitHub

### Exit criteria
- [ ] Core happy path and key failure paths are covered before launch

---

## 15. Deployment and Release

- [x] Pick MVP hosting target
- [ ] Separate dev / staging / production env vars
- [x] Add production compose or deployment manifests
- [x] Set HTTPS and domain
- [ ] Configure persistent Postgres storage
- [ ] Configure Redis persistence/recovery expectations
- [ ] Add backup strategy for DB
- [x] Add rollout + rollback instructions
- [ ] Document how to rotate webhook secret and GitHub App key

### Exit criteria
- [ ] A maintainer can deploy the app, survive a restart, and recover from a bad release

---

## 16. Launch Readiness

- [ ] Dogfood on your own repo
- [ ] Dogfood on a second repo with different contribution patterns
- [ ] Review top false positives
- [ ] Review top false negatives
- [ ] Tune score thresholds
- [ ] Tune duplicate threshold
- [ ] Write install guide
- [ ] Write admin troubleshooting guide
- [ ] Write known limitations page

### Exit criteria
- [ ] You trust it enough to let another maintainer try it without sitting next to them

---

## 17. Recommended Build Order

1. Webhook intake
2. Persistence
3. Background worker
4. AI scoring
5. GitHub write-back
6. Dashboard inbox
7. Duplicate detection
8. Feedback loop
9. Observability and deployment hardening

---

## 18. Current Status

### Done now
- [x] Repo scaffold started
- [x] Production MVP checklist written
- [x] FastAPI webhook skeleton added
- [x] Local tests for webhook behavior added

### Next best moves
- [ ] Run Phase 1 locally
- [ ] Register the GitHub App
- [ ] Add installation event handling
- [ ] Add real queue integration
- [ ] Persist incoming webhook events

# maintainerKi Production MVP Checklist

This checklist turns the README vision into a production-minded MVP that is still small enough to ship.

---

## 1. Product Definition

### Core promise
- [x] maintainerKi receives new GitHub issues and pull requests
- [x] maintainerKi scores them for triage value
- [x] maintainerKi flags likely duplicates or suspicious submissions
- [x] maintainerKi suggests labels and priority
- [x] maintainer always remains the final decision-maker

### MVP success criteria
- [x] A maintainer installs the GitHub App on one or more repos
- [x] New issues and PRs appear in maintainerKi within a few minutes
- [x] Each contribution gets an analysis record with score, summary, and suggested labels
- [x] The maintainer can open a dashboard and work a sorted inbox
- [x] False positives are visible and easy to override
- [x] Basic observability exists so production failures are discoverable

### Explicit non-goals for MVP
- [x] No auto-closing of issues or PRs
- [x] No auto-merging
- [x] No fully autonomous moderation
- [x] No marketplace-scale multi-tenant billing in MVP
- [x] No advanced learning loop that retrains custom models

---

## 2. MVP Scope Lock

### P0: must ship
- [x] GitHub App registration flow documented
- [x] Webhook receiver with signature verification
- [x] Background job queue for async processing
- [x] Persistence layer for repositories and contributions
- [x] AI scoring for quality / relevance / completeness / suspicion
- [x] Suggested labels written back to GitHub
- [x] Duplicate detection for issues and PRs
- [x] Dashboard inbox with filters and detail view
- [x] Maintainer feedback action for “good score” / “wrong score”
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
- [x] Create dashboard directory structure
- [x] Add `.gitignore`
- [x] Add `.env.example`
- [x] Add `requirements.txt`
- [x] Add `docker-compose.yml`
- [x] Add `Makefile` or task runner commands
- [x] Add project README at repo root when codebase becomes canonical
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
- [x] Handle webhook delivery replay safely
- [x] Add idempotency protection for duplicated deliveries

### Exit criteria
- [x] A real GitHub webhook from a test repository reaches local dev and is accepted
- [x] Invalid signatures are rejected
- [x] Supported events are turned into queued jobs

---

## 5. Background Processing

- [x] Add Celery worker
- [x] Add Redis broker config
- [x] Create “process contribution” task
- [x] Pass only the minimal required payload to the worker
- [x] Add retries with backoff for transient failures
- [x] Mark permanent failures clearly
- [ ] Add dead-letter or failure logging strategy

### Exit criteria
- [x] The API returns to GitHub quickly
- [x] Processing still completes asynchronously even if scoring takes 30-60 seconds

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
- [x] Add Alembic migrations
- [x] Define retention policy for raw payloads
- [ ] Decide whether to store diffs in full or summarized form
- [x] Define indexing strategy for repo lookup, status, created time, score, and duplicate search

### Exit criteria
- [x] A processed GitHub contribution becomes a queryable record in PostgreSQL

---

## 7. AI Scoring Engine

### Functional work
- [x] Build LLM client abstraction
- [x] Support at least one provider for MVP
- [x] Add provider config via environment variables
- [x] Create prompt template with strict JSON output
- [x] Parse model response robustly
- [x] Fail closed when model output is malformed
- [x] Compute overall score from category scores
- [x] Save raw score breakdown and one-sentence explanation

### Product quality work
- [ ] Define score semantics clearly
- [ ] Define suspicion scoring examples
- [x] Define label mapping rules from score ranges
- [x] Add prompt versioning
- [ ] Add evaluation fixtures with expected outputs

### Operational concerns
- [x] Set timeout budget
- [x] Add retry policy for provider/network failures
- [ ] Add fallback behavior when the model is unavailable
- [ ] Log token cost / request duration if using a paid provider

### Exit criteria
- [x] A new issue or PR receives consistent structured scoring without blocking webhook response

---

## 8. Duplicate Detection

- [x] Choose embedding provider for MVP
- [x] Create title + body normalization rules
- [x] Generate embeddings for contributions
- [x] Store embeddings safely
- [x] Compare against repo-local history only
- [x] Return top N similar items with scores
- [x] Set similarity threshold and document why
- [x] Add dashboard display for duplicate candidates
- [x] Add GitHub label for likely duplicates

### Scale path
- [ ] Use JSON vector storage first or adopt pgvector early
- [ ] Plan migration path if repo size grows

### Exit criteria
- [x] Two semantically similar issues are surfaced as likely duplicates in the UI and labels

---

## 9. Labeling and GitHub Write-Back

- [x] Authenticate as GitHub App installation
- [x] Fetch installation token safely
- [x] Create or apply maintainerKi labels
- [x] Avoid clobbering human-applied labels
- [ ] Add optional GitHub comment with summary
- [x] Record write-back result and failures
- [ ] Rate-limit outbound GitHub API calls

### Exit criteria
- [x] After analysis, GitHub visibly shows the suggested triage labels

---

## 10. Dashboard MVP

### Inbox page
- [x] Repo selector
- [x] Sorted queue
- [x] Filters by type, status, score, suspicion, duplicate
- [x] Search by title / author / number
- [x] Empty states
- [x] Error states
- [x] Loading states

### Detail page
- [x] Full issue / PR metadata
- [x] Score breakdown
- [x] AI summary
- [x] Suggested labels
- [x] Duplicate candidates
- [x] Direct link to GitHub
- [x] Feedback controls

### MVP stats
- [x] Queue depth
- [x] Pending vs reviewed counts
- [x] Average processing latency

### UX quality
- [ ] Keyboard navigation works
- [ ] Responsive layout works on laptop widths
- [ ] Contrast and focus states are visible

### Exit criteria
- [x] A maintainer can triage their inbox from the dashboard without opening raw database records

---

## 11. Maintainer Feedback Loop

- [x] Record “agreed” vs “wrong score”
- [x] Record corrected labels
- [x] Record duplicate confirmation or dismissal
- [x] Show feedback state in dashboard
- [ ] Export feedback for later evaluation work

### Exit criteria
- [x] Maintainers can tell the system when it got something wrong, and the signal is stored for later improvement

---

## 12. Security, Abuse, and Privacy

- [x] Validate webhook signatures
- [x] Keep secrets out of source control
- [x] Add request size limits
- [x] Add structured input validation
- [x] Add rate limiting where appropriate
- [ ] Sanitize or escape any user-generated content rendered in dashboard
- [ ] Decide whether raw PR bodies and diffs are stored permanently
- [x] Document PII handling and retention
- [ ] Minimize sensitive log contents
- [ ] Rotate GitHub credentials safely

### Exit criteria
- [x] The app has a documented secrets strategy, basic abuse protections, and no obvious unsafe ingest path

---

## 13. Observability and Operations

- [ ] Structured application logs
- [x] Request IDs / delivery IDs in logs
- [x] Worker logs with job IDs
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
- [x] Score parsing
- [x] Label mapping
- [x] Duplicate similarity thresholds

### Integration tests
- [x] Webhook -> queue -> DB flow
- [ ] Worker -> model client -> save result flow
- [ ] GitHub App token + label write-back
- [x] Dashboard API endpoints

### End-to-end tests
- [x] Test repo sends webhook
- [x] Contribution appears in dashboard
- [x] Labels show up on GitHub

### Exit criteria
- [x] Core happy path and key failure paths are covered before launch

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

- [x] Dogfood on your own repo
- [ ] Dogfood on a second repo with different contribution patterns
- [ ] Review top false positives
- [ ] Review top false negatives
- [ ] Tune score thresholds
- [ ] Tune duplicate threshold
- [x] Write install guide
- [x] Write admin troubleshooting guide
- [x] Write known limitations page

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
- [x] GitHub webhook intake, signature verification, and replay/idempotency handling
- [x] Background queue + worker path
- [x] PostgreSQL/Redis production compose path
- [x] AI scoring with provider abstraction (`mock`, `ollama`, `mlx`)
- [x] Duplicate detection with dashboard visibility and GitHub duplicate comment support
- [x] Dashboard inbox, detail view, filters, stats, and feedback loop
- [x] Dashboard browser E2E coverage for login, inbox, detail, feedback, and logout
- [x] Production-like Compose smoke validation with a stubbed GitHub App API
- [x] Setup wizard, smoke test, source snapshot export, and self-hosted docs
- [x] Hosted hardening for docs exposure, public health detail, trusted hosts, and admin auth
- [x] Python dependency audit cleanup completed for the pinned requirements set
- [x] Beta-level self-hosted release evidence: clean production-like Compose smoke, dashboard E2E, fixture webhook replay, and real GitHub label write-back tested

### Next best moves
- [ ] Dogfood on multiple real repositories over time
- [ ] Add full multi-user auth / roles if the product grows past single-admin self-hosting
- [ ] Add broader public-edge protections and release automation if pursuing marketplace/public SaaS
- [ ] Expand end-to-end deployment validation on a real VPS/domain

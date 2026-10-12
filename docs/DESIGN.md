# Reliability design

DataGuard is a modular monolith. The API owns ingestion, immutable configuration creation, authorization, and user actions. Celery workers execute the same pure validation and transactional processing modules. PostgreSQL is authoritative; Redis transports notifications. The Next.js UI uses a typed request client and polls authoritative API state every three seconds.

## Data flow and transaction boundaries

1. Ingestion validates UTF-8, CSV structure, limits, and headers before committing a dataset, original bytes, hash, input rows, configuration v1, and audit event in one transaction. CSV row numbers are logical records, not physical text lines (quoted newlines are supported). The 10 MiB / 100,000-row limits bound ingestion memory; this is not a streaming unlimited upload service.
2. Run creation commits the run and audit event before attempting broker publication. A beat task scans queued and expired running runs every five seconds. Failed publication cannot discard the run. This durable scanner substitutes for a separate transactional outbox in this small application.
3. A worker locks the run, checks terminal state and lease expiry, and creates a fresh random fencing token. Attempts are limited to five per recovery cycle. A schema failure is permanent and finishes immediately without row writes.
4. Each batch locks the run and then its dataset. The run token, active state, and unexpired lease are checked inside the same transaction. Accepted writes use nested savepoints so a uniqueness violation quarantines only that row. All other row errors, quarantine writes, replay outcomes, aggregate counters, the checkpoint, and lease renewal commit together. A failed batch rolls everything back.
5. The next batch starts from the persisted ordinal checkpoint. Expired workers cannot commit with an old token. A worker holding a row lock may delay another transaction; the lease does not forcibly break PostgreSQL locks. Process death closes its connection, allowing takeover.
6. Completion computes the actual rejected fraction. Exceeding the configured maximum marks the run failed but retains accepted records and rejected evidence. This is a quality gate, not atomic dataset publication.

## Delivery and duplicate semantics

Execution is **at least once**, not exactly once. Celery uses late acknowledgments, reject-on-worker-loss, prefetch one, and a 60-second Redis visibility timeout. Duplicate publication is safe because ownership of work is established in PostgreSQL. Task operational retries use bounded exponential backoff (2, 4, 8, 16 seconds, capped at 30); lease scanning recovers abandoned work independently. Code failures also consume the five-attempt durable budget. Validation failures never trigger infrastructure retries.

Accepted records have both unique (run_id, row_number) and unique (dataset_id, business_key) constraints. The business key is SHA-256 over canonical JSON of normalized configured unique-key fields, in fixed order. Unique-key field names, types, date formats, and ordering cannot change within a dataset. Hash collision risk is accepted for this portfolio demo; a production system could also store and constrain full keys.

- Within a file: the first valid row for a business key wins. Subsequent valid duplicate keys are rejected. An invalid row does not reserve a key.
- Across runs of the same dataset: already accepted keys are rejected, including when rules are relaxed. Runs are independently auditable; revalidation does not overwrite accepted records.
- Across separately uploaded datasets: keys are independent. Re-uploading the same bytes creates a new dataset intentionally. The content hash is provenance, not upload deduplication.
- During replay: the same dataset business-key constraint applies. Correcting a duplicate requires a genuinely distinct key or leaving the row quarantined. Repeated delivery of a completed replay cannot add records.

## Crash recovery, cancellation, and known failure cases

Run leases default to 15 seconds and are renewed each batch. The beat scanner republishes when an expired lease is observed. If Redis is unavailable, durable work waits until broker and beat recover. PostgreSQL downtime rolls back an open batch; a subsequent recovery resumes at the last committed checkpoint. If beat is stopped, manual recovery is available, but eventual automatic recovery requires beat and a worker to be running. A live lease cannot be forcibly stolen through the API.

A hard worker kill before commit rolls back the batch. A hard kill after commit preserves the checkpoint and writes. The subprocess recovery script really kills an OS process after its first commit, waits for natural lease expiry, and resumes. The Docker interruption script additionally exercises Celery, Redis, and the scheduler. Results from these two paths are labeled separately.

Cancellation obtains the same run lock, fences subsequent batches, and retains committed evidence. Cancelling a replay restores unprocessed quarantine records to corrected status so the user can enqueue a new replay. Manual recovery resets the bounded attempt cycle only for queued, abandoned, or infrastructure-failed runs; it cannot replay permanent validation failures. A malformed new configuration must be fixed and versioned before starting a new run.

A process can fail mid-claim or mid-batch. Claims and batches are separate transactions by design. Input and configurations are immutable through the API. The relational constraints are the final protection even if a task is accidentally published twice. Dataset locking serializes competing runs within one dataset; this favors correctness over parallel throughput. The tested SQLite fallback has explicit transaction BEGIN and foreign keys but is a **single-worker development option**, not a replacement for PostgreSQL row locks.

## Quarantine and correction

Rejected originals, failure lists, source references, configuration IDs, and timestamps never change. The corrected field stores the latest proposal. Every successful correction writes the full proposal to an append-only audit event, preserving past proposals. Corrections are checked against the original configuration and current accepted keys before saving. Replay snapshots proposal values into immutable ReplayItem rows before enqueueing. One replay uses one dataset and one original configuration; mixed selections are rejected.

Conflicts may arise between correction validation and execution. Replay revalidates and checks the database uniqueness constraint at write time. Outcomes are recorded per replay item. Failed replay retains the original quarantine record; no replacement evidence is created. Queued and successfully replayed records cannot be edited. Original values are intentionally visible to their owner in the UI and audit detail; structured logs contain identifiers and events rather than raw records.

## Normalization and warnings

String values are trimmed; absent or blank values become null. Types are explicitly parsed. Numbers use Decimal, reject NaN/infinity/grouping notation, and are stored as decimal text to avoid floating-point loss. Integer columns reject fractional values. Dates parse with the configured strptime pattern and store ISO calendar dates. Allowed values compare trimmed original text, case-sensitively. Unexpected columns warn, reject the dataset, or are allowed according to policy; extras stay in original evidence and are excluded from accepted normalized values. Warnings do not reject rows. Missing required headers fail the dataset before processing. Maximum failure rate applies to row rejection, including duplicate-key failures.

## Connector security and authentication

Connector requests choose a named endpoint from an administrator-owned mapping. Users cannot supply destinations, redirects, or next-page URLs. Pagination is bounded numeric page/size to the same exact endpoint, with three transient attempts per page, five-second request timeouts, a shared 10 MiB response budget, and a 100,000-row cap. Redirects and non-429 client errors are permanent. Credentials come from server environment and are never returned to the UI or logged. An administrator can intentionally configure a private network destination (the offline mock is one); deployment must trust and review that mapping and apply outbound network policy. DNS rebinding by a malicious configured host is not separately mitigated.

Authentication follows FastAPI's OAuth2 password flow with Argon2 hashing and signed, expiring JWTs (issuer and audience verified). Dataset ownership is checked before file access, configuration mutation, run actions, and correction/replay. Lists filter by owner. The UI stores the bearer token in session storage for the local demo; production should add secure HttpOnly sessions or an established OIDC provider, TLS, login throttling, and account lifecycle management. There is no open registration endpoint.

## Scope and tradeoffs

PostgreSQL stores original bytes and row JSON for a reproducible compact demo; object storage would be a better fit for larger inputs. Transactions process 250 rows by default. Input limit, modest batch size, and one worker keep this achievable by one student. Optional statistical detection is deferred. A measured quality trend is a view of validation outcomes, not statistical drift detection. No LLM or paid API is required.

Reference documentation checked: [Celery task semantics](https://docs.celeryq.dev/en/v5.5.0/userguide/tasks.html), [SQLAlchemy SQLite transactions](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#transactions-with-sqlite-and-the-sqlite3-driver), [FastAPI OAuth2 and JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/), [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).

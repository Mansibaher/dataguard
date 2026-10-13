# DataGuard

**Data quality and pipeline monitoring with evidence you can inspect.** A complete local portfolio application built with Next.js, TypeScript, Tailwind, FastAPI, Pydantic, PostgreSQL, SQLAlchemy, Alembic, Celery, and Redis.

Upload a sales CSV, preview it, version its validation rules, process it in bounded batches, inspect accepted and quarantined records, recover interrupted work, correct records, and replay them with an audit trail. All bundled data is **synthetic**. No paid keys or hosted services are required.

![DataGuard dashboard](docs/dashboard.png)

## Start the full application

Requires Docker Desktop with its Linux engine running, or Docker Engine + Compose on Linux. From the repository root:

~~~sh
cp .env.example .env
# PowerShell alternative: Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --build
~~~

Open [DataGuard](http://localhost:3000). Docker exposes the API on port 8001 and keeps PostgreSQL internal to avoid conflicts with other local projects. API explorer: [FastAPI docs](http://localhost:8001/docs). Migration and seed jobs run before the application services.

**Clearly labeled local demo login:** `demo@dataguard.local` / `dataguard-demo`. These defaults are for local synthetic demonstrations. Existing password hashes are preserved on re-seed; changing DEMO_PASSWORD only affects creation of the demo account.

## Main demo

1. Click **Add dataset** and upload `demo-data/synthetic-demo.csv`.
2. Review the original values in the CSV preview. The file has 40 rows, eight bad records, and an unexpected campaign column.
3. Review schema rules; keep unexpected-column policy at Warn and maximum failure rate at 25%. Click **Save & start validation**.
4. Inspect **32 accepted / 8 rejected**, warnings, failure counts, configuration version, duration, and throughput.
5. Open Quarantine, filter a failure reason, inspect original evidence, enter a corrected proposal, and click Validate & save correction.
6. Select corrected records from the same dataset/configuration and click Replay. Inspect per-record outcomes and the audit trail.
7. Demonstrate interruption separately with the scripts below. See `docs/DEMO.md` for a three-minute presentation.

The seeded clean dataset has 40 valid rows. The seeded investigation dataset has four failures (36 accepted); the uploaded demo file intentionally has eight failures. Configurations and source provenance are preserved per dataset/run.

## Architecture

~~~mermaid
flowchart LR
  UI[Next.js interface] --> API[FastAPI / ownership checks]
  API --> PG[(PostgreSQL: inputs, rules, runs, evidence)]
  API --> Redis[(Redis task delivery)]
  Beat[Celery beat durable scanner] --> PG
  Beat --> Redis
  Redis --> Worker[Celery worker]
  Worker --> PG
  Mock[Synthetic HTTP source] --> API
~~~

The API and worker run separately inside a modular monolith. PostgreSQL stores original bytes, content hashes, input rows, immutable configurations, durable checkpoints and leases, accepted business keys, quarantine evidence, correction snapshots, and audit events. Redis can be restarted without losing authoritative work state. The scheduler republishes queued or abandoned runs.

**At-least-once execution; no exactly-once claim.** Each batch commits output records, failures, counters, checkpoint, and lease renewal together. Run fencing tokens and database uniqueness constraints prevent duplicate accepted writes. Duplicate keys within the same dataset are rejected, including across runs and replay; separately uploaded datasets have separate key scope. Configuration snapshots and original evidence are preserved. See `docs/DESIGN.md` for transaction boundaries, lock ordering, normalization, failure-rate semantics, recovery assumptions, and tradeoffs.

## Repository

- `backend/app/`: authentication, data model, ingestion, validation, API, transactional processing, Celery worker, mock source, and seed.
- `backend/migrations/`: frozen initial schema and Alembic revision.
- `backend/tests/`: behavior, isolation, rollback, recovery, connector, replay, and PostgreSQL concurrency tests.
- `frontend/`: Next.js interface, maintained typed API client, and Playwright demo.
- `demo-data/`: small synthetic clean/invalid/duplicate/schema/demo CSVs.
- `scripts/`: deterministic generator, scoped reset, and Docker worker interruption demo.
- `backend/scripts/`: measured benchmark, actual subprocess crash recovery, and portable development runner.
- `docs/`: design, deployment, demo, verification, resume bullets, measurements, and screenshots.
- `.github/workflows/ci.yml`: PostgreSQL tests and full Compose/browser CI.

## Validation

Required columns, string/integer/number/date types, non-null fields, numeric bounds, allowed values, date patterns, fixed unique keys, unexpected-column policy, and maximum failure rate are configurable. Rules are versioned through the UI. Strings trim whitespace; blanks become null. Invalid numbers and dates are rejected rather than repaired silently. Decimal numbers are stored as text to avoid binary floating-point loss.

A missing required column fails the dataset before row processing. Unexpected columns can warn, reject, or be allowed; they remain in original evidence. Rows failing validation go to quarantine with actionable messages. Exceeding maximum row failure rate marks a run failed **while retaining committed accepted records and quarantine evidence**; it does not roll back the entire dataset.

## Tests

~~~sh
# From the repository root, test against a fresh dedicated database.
docker compose exec postgres createdb -U dataguard dataguard_test
docker compose exec -e TEST_DATABASE_URL=postgresql+psycopg://dataguard:dataguard@postgres:5432/dataguard_test api python -m pytest -q
cd frontend
npm ci
npx playwright install chromium
npm run typecheck
npm test
~~~

Test fixtures drop application tables and refuse database names without `test`. Never point tests at the main application database. PostgreSQL is required to verify real row-lock concurrency. SQLite fallback tests are useful for fast feedback but cannot prove PostgreSQL lock semantics. Browser tests require API and processing worker to be running. See `docs/VERIFICATION.md` for what was actually executed on the build host.

## Benchmarks and real process recovery

~~~sh
# Run from backend (locally with DATABASE_URL set, or inside the API container):
python scripts/benchmark.py --rows 10000 100000 --output ../docs/benchmark-results.json
python scripts/recovery.py --rows 2000 --output ../docs/recovery-results.json
~~~

The benchmark uses fixed-seed data with four known failures, asserts exact acceptance/quarantine counts, repeats completed task delivery twice, records end-to-end and processing duration, throughput, and traced peak Python allocation. It calls the production processing function directly and excludes broker delivery overhead. Tracemalloc changes timing and does not measure total process RSS. Run with a seeded database and **without competing workers or schedulers** against the same evaluation database. For direct scripts inside Compose, stop worker and scheduler temporarily, execute the scripts in the API container, copy the reports out with `docker compose cp`, and restart worker/scheduler afterward. Prefer a dedicated evaluation database. Results are actual measurements, not production guarantees.

The subprocess recovery script hard-kills a real processing process after one committed batch, waits for natural lease expiry, then resumes. It proves the processing/database crash path; it does not prove Redis/Celery transport behavior.

For a full Celery interruption demonstration, set `BATCH_DELAY=0.1` in .env and recreate the worker. From the repository root:

~~~sh
docker compose up -d --force-recreate worker
python scripts/worker-interruption.py
~~~

This uploads 100,000 synthetic clean rows, observes a committed partial checkpoint, sends SIGKILL to the Celery worker, restarts it, waits for scheduler recovery, and asserts 100,000 accepted records with zero duplicates. It writes `docs/celery-recovery-results.json` only after successful assertions. The full Compose stack now runs after a Docker runtime repair. This dedicated Celery interruption script has not yet been executed; see the verification ledger for exact scope.

Generate larger fixtures without committing them:

~~~sh
python scripts/generate.py --rows 100000 --variant demo --output demo-data/large-sales.csv
~~~

## Connector

The bundled mock-source container returns paginated flat sales objects offline. The UI configures allowed source name, page size, and maximum pages. Destinations come from an administrator-owned CONNECTOR_SOURCES mapping; arbitrary user URLs, redirect destinations, and server-provided next-page URLs are never followed. Five-second request timeouts, three bounded attempts per page, response-size and row limits, and bounded pages keep requests controlled. Optional CONNECTOR_TOKEN stays server-side. To add a real connector, configure its exact endpoint server-side; follow the documented `rows` / `has_more` response contract.

## Portable development without Docker

Python 3.11 and Node 22 are supported. PostgreSQL is preferred. SQLite is available for a single-worker local fallback:

~~~sh
# Backend terminal, from backend:
python -m venv .venv
# Activate .venv using your shell's normal activation command.
pip install -r requirements-lock.txt
alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 127.0.0.1 --port 8000
# Second backend terminal, same DATABASE_URL:
python scripts/local_worker.py
# Optional source terminal:
uvicorn app.mock_source:app --host 127.0.0.1 --port 8090
# Frontend terminal, from frontend:
npm ci
npm run dev
~~~

The portable worker polls PostgreSQL/SQLite and uses the production transactional core. It is a development option, not Celery delivery. For native HTTP connector imports set CONNECTOR_SOURCES to `{"demo":"http://127.0.0.1:8090/sales"}` on the API before startup. For PostgreSQL set DATABASE_URL on every backend terminal to the same SQLAlchemy psycopg URL. Native Celery needs a running Redis broker and a separate `celery -A app.worker.celery beat` process.

## Explicit demo reset

~~~sh
docker compose exec api python -m app.seed --reset-demo-data
~~~

This deletes only the seeded demo account's data and refuses if its jobs are active. It preserves other users and does not delete volumes. Cancel or finish demo jobs first. Normal seeding is idempotent and preserves existing inputs.

## Troubleshooting

- **Docker pipe/daemon errors:** start Docker Desktop and confirm the Linux engine is healthy. Docker must work before Compose can run; code generation cannot fix disabled virtualization or a failed WSL backend.
- **Run remains queued:** check worker, Redis, and scheduler containers. PostgreSQL still retains the run. Restart services or use manual recovery after lease expiry.
- **Recover button says live lease:** wait at least 15 seconds after the process stops; the API prevents stealing live work. Scheduler checks every five seconds.
- **Failed after too many bad rows:** inspect the failure-rate threshold. Accepted rows are retained. Fix the input or create a new rule version and run. Re-running the same dataset will reject already accepted keys.
- **Correction still fails uniqueness:** the accepted key already exists; use a distinct legitimate transaction key. Replay cannot overwrite accepted records.
- **Browser cannot reach API:** verify NEXT_PUBLIC_API_URL build argument and FRONTEND_ORIGIN CORS setting. HTTPS deployment needs an HTTPS API URL.
- **Seed password changed but login did not:** seeding never overwrites an existing user's password hash. Use a fresh demo database or an intentional account-management workflow.

## Limitations

Single VM / no HA, one worker by default, dataset-level serialized writes, bounded ingestion memory, PostgreSQL storage for originals, no object storage, no public registration or OIDC, no login throttling, local bearer session storage, no token revocation, no production security audit, and no automatic classification beyond explicit rules. Statistical drift detection is intentionally deferred. An append-only API audit trail is not tamper-proof against a database administrator. Large tables use pagination; selection is restricted to the currently loaded quarantine page. Dataset names in run lists fall back to IDs when their metadata is outside the loaded library page. Credentials, reset commands, and Docker port defaults are intended for local synthetic demos.

Deployment guidance: `docs/DEPLOYMENT.md`. Verified results and grounded resume bullets: `docs/VERIFICATION.md` and `docs/RESUME.md`.

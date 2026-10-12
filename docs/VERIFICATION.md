# Verification ledger

Build date: October 12, 2026 (America/Los_Angeles). Results below distinguish real tests from supplied but unexecuted deployment paths.

## Executed

- Backend behavioral suite: **23 passed** against a real PostgreSQL 16.8 server, including concurrent delivery, partial-batch rollback, lease fencing, accepted-key duplicate prevention, version reproducibility, schema policies, cancellation, correction replay, failed replay outcomes, source retries, ownership, and file isolation. Most recent run: 16.99 seconds. One third-party test-client deprecation warning.
- SQLite development suite: **22 passed, 1 skipped** (PostgreSQL concurrency requires row locks). An initial failed partial-batch rollback test exposed sqlite3 legacy transaction behavior; explicit BEGIN and foreign keys fixed it before rerunning.
- Next.js 16.4.0 production build and TypeScript checks: passed. npm audit: **0 vulnerabilities** at the executed audit; this is a point-in-time dependency audit, not a security certification.
- Playwright browser scenarios: **2 passed against native PostgreSQL (18.4 seconds)** for CSV correction/replay and the real paginated mock HTTP import. The initial SQLite-backed demo also passed (one test, 14.5 seconds), including 40-row upload, preview, configurable rules, 32 accepted / 8 rejected, correction, successful replay, audit events, desktop/mobile screenshots, no browser page errors, and no horizontal viewport overflow.
- PostgreSQL process hard-kill recovery: passed. An actual OS process was stopped after **250 committed rows** and recovered **2,000 total accepted rows** with **0 duplicate writes** and two processing attempts. Recovery including lease expiry: **19.22 seconds**. Exact output: recovery-results.json. This invokes the production processing core; Redis/Celery transport is excluded.
- 10,000-row PostgreSQL benchmark: passed. **9,996 accepted / 4 quarantined**, exactly matching the known synthetic failures. **0 additional accepted writes** after two repeated completed deliveries. Processing duration **75.24 seconds**, **132.91 rows/second**; end-to-end duration **77.40 seconds**. Traced peak Python allocation **9,027,682 bytes**. Tracemalloc is enabled and affects timing; this is not total RSS. Exact values and environment: benchmark-results.json.
- Compose configuration validation: passed with `docker compose config --quiet`.
- Alembic upgrade and deterministic demo seeding: executed successfully on SQLite and native PostgreSQL.

## Final 100,000-row measurement

The PostgreSQL benchmark completed and all count/idempotency assertions passed:

| Rows | Accepted | Quarantined | Duplicate writes after two redeliveries | Processing duration | Rows/s | End-to-end duration | Peak traced Python allocation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10,000 | 9,996 | 4 | 0 | 75.24 s | 132.91 | 77.40 s | 9,027,682 bytes |
| 100,000 | 99,996 | 4 | 0 | 752.39 s | 132.91 | 801.31 s | 85,339,731 bytes |

Both inputs contain exactly four known failures. End-to-end includes ingestion and repeated-delivery assertions; fixture generation and Redis delivery are excluded. Timings use tracemalloc, and other development servers/tests shared the host. These are reproducible local correctness measurements, not production capacity estimates.

The final standalone Next.js server served both browser scenarios successfully. Repeated demo tests are scoped to the newly created replay ID so prior audit events cannot create ambiguous selectors.

## Environment and limits

Windows host, Python 3.11.9, Node 22.14.0, native PostgreSQL 16.8 bound to loopback on port 55432. AMD Ryzen 5 PRO 7540U, 6 physical / 12 logical cores, 16,405,434,368 bytes installed RAM. The processing benchmark records batch size 250, OS, CPU count, Python, and database dialect. Peak memory is Python allocation tracing, not database/Redis memory or complete process memory. Browser verification uses the portable database polling worker; production Compose uses Celery.

## Not executed on this host

Docker Desktop's Linux engine did not initialize, so the complete Compose service startup, Redis-backed Celery delivery, Celery worker SIGKILL/restart integration script, container builds, and GitHub Actions jobs are **not runtime-verified here**. The Docker manifest parsed successfully; native PostgreSQL verifies database behavior independently. The CI workflow includes the full Compose/browser path for a Linux runner. No successful CI result or Docker recovery result is claimed.

No hosted deployment was attempted: this request is a local repository build with a practical deployment guide. Optional statistical drift detection is deferred. No production-readiness or exactly-once execution claim is made.

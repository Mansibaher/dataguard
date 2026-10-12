# Grounded resume bullets

- Built DataGuard, a full-stack data quality platform using Next.js, FastAPI, PostgreSQL, and versioned configurable validation, with CSV/HTTP ingestion, quarantine correction/replay, and ownership-scoped audit history.
- Implemented transactional batch checkpoints, worker leases, fencing tokens, and database uniqueness constraints; verified recovery of 2,000 rows after a hard process kill with zero duplicate accepted writes and 23 passing PostgreSQL behavioral tests.
- Created deterministic 10,000/100,000-row benchmarks and two Playwright browser workflows; validated 99,996 accepted / 4 quarantined records on the 100,000-row run with zero duplicate writes after repeated delivery, measuring 132.91 rows/second with allocation tracing enabled.

Interview caveats: measured recovery exercises the processing/database core, and browser checks use the portable worker. Redis-backed Celery interruption and the full Docker runtime were not executable on this host. Timing includes tracemalloc and concurrent development/test activity; these local results are not a production capacity claim.

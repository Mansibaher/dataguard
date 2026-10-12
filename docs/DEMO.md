# Three-minute demo

All bundled records are synthetic. Sign in with the clearly labeled local demo account.

**0:00–0:25 — Problem and input.** Explain: "DataGuard validates sales records and preserves evidence when processing fails." Click Add dataset, upload `demo-data/synthetic-demo.csv`. Show the preview, missing customer IDs, bad amounts, duplicate transaction IDs, and unexpected campaign column.

**0:25–0:55 — Rules and versioning.** Review transaction_id as the fixed unique key, required/non-null fields, numeric range, currency allowed values, date pattern, warn-on-unexpected-columns, and 25% failure-rate threshold. Click Save & start validation. Show the configuration version retained in run details.

**0:55–1:20 — Understandable outcomes.** The 40-row synthetic demo has 32 accepted and 8 quarantined: two each for missing customer ID, negative amount, invalid amount type, and duplicate key. The campaign column is a warning and does not reject the dataset. Show rule counts, pass rate, accepted explorer, and the original input download.

**1:20–1:55 — Recovery evidence.** Present the verified recovery report: a separate process is hard-killed after a committed batch, lease expires, and processing resumes from its checkpoint with no duplicate accepted writes. When Docker works, prepare the larger job in advance with BATCH_DELAY=0.1 and use `scripts/worker-interruption.py` to demonstrate an actual Celery worker SIGKILL and restart. Do not call the subprocess measurement a verified Redis/Celery recovery result.

**1:55–2:35 — Correction and replay.** Open Quarantine and filter non-null failures. Show the immutable original customer_id and failure message. Enter a corrected customer ID, validate and save. Select that corrected record and Replay. Show successful per-record outcome and original configuration version. Explain that a duplicate transaction needs a distinct real key; replay does not bypass constraints.

**2:35–3:00 — Audit and engineering claims.** Show correction, replay, and recovery audit events. State "at-least-once execution with transactional checkpoints, fencing, and unique constraints," rather than exactly-once execution. Open VERIFICATION.md to distinguish actual PostgreSQL/browser/benchmark results from the unverified Compose runtime. Discuss the single-worker and 10 MiB limits candidly.

## Reset between demos

Cancel or finish active demo runs first. From the repository root run `docker compose exec api python -m app.seed --reset-demo-data`. This deletes only records owned by the seeded demo account and refuses active jobs. It does not delete volumes or unrelated users' data. Commands are also provided in scripts/demo-reset.ps1 and scripts/demo-reset.sh.

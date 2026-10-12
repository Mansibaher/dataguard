import logging
import os
import time
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import Session
from .models import (
    Dataset,
    Configuration,
    Run,
    InputRow,
    Quarantine,
    ReplayItem,
    Accepted,
    audit,
    uid,
    now,
)
from .validation import dataset_issues, validate, business_key, issue

log = logging.getLogger("dataguard.processing")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "250"))
LEASE_SECONDS = int(os.getenv("LEASE_SECONDS", "15"))
MAX_ATTEMPTS = 5
TERMINAL = {"completed", "completed_with_errors", "failed", "cancelled"}


def claim(run_id):
    with Session.begin() as db:
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if not run or run.state in TERMINAL:
            return None
        if run.lease_until and run.lease_until > now():
            return None
        dataset = db.get(Dataset, run.dataset_id)
        if run.attempts >= MAX_ATTEMPTS:
            run.state = "failed"
            run.error_kind = "infrastructure"
            run.error = "Recovery attempts exhausted"
            run.finished_at = now()
            audit(db, dataset, "run.attempts_exhausted", run.id)
            return None
        recovering = run.state == "running"
        run.error = None
        run.error_kind = None
        run.attempts += 1
        run.state = "running"
        run.started_at = run.started_at or now()
        run.lease_token = uid()
        run.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        audit(
            db,
            dataset,
            "run.recovered" if recovering else "run.started",
            run.id,
            attempt=run.attempts,
            checkpoint=run.processed,
        )
        if run.kind == "initial":
            failures, warnings = dataset_issues(
                dataset.columns, db.get(Configuration, run.configuration_id).rules
            )
            run.warnings = warnings
            if failures:
                run.state = "failed"
                run.error_kind = "validation"
                run.error = (
                    "Dataset schema failed; change rules or input and start a new run"
                )
                run.failures = {
                    f["rule"]: sum(x["rule"] == f["rule"] for x in failures)
                    for f in failures
                }
                run.warnings = warnings + failures
                run.finished_at = now()
                run.lease_token = None
                run.lease_until = None
                audit(db, dataset, "run.schema_failed", run.id, failures=failures)
                return None
        return run.lease_token


def batch(run_id, token, failpoint=None):
    with Session.begin() as db:
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if (
            not run
            or run.state != "running"
            or run.lease_token != token
            or run.lease_until < now()
        ):
            return False
        # Serialize business-key decisions for a dataset; lock ordering is run then dataset everywhere.
        dataset = db.scalar(
            select(Dataset).where(Dataset.id == run.dataset_id).with_for_update()
        )
        rules = db.get(Configuration, run.configuration_id).rules
        entity = ReplayItem if run.kind == "replay" else InputRow
        predicate = (
            entity.run_id == run.id
            if run.kind == "replay"
            else entity.dataset_id == dataset.id
        )
        rows = db.scalars(
            select(entity)
            .where(predicate, entity.number > run.processed)
            .order_by(entity.number)
            .limit(BATCH_SIZE)
        ).all()
        counts = dict(run.failures)
        for row in rows:
            normalized, failures = validate(row.values, rules)
            q = db.get(Quarantine, row.quarantine_id) if run.kind == "replay" else None
            if not failures:
                key = business_key(normalized, rules)
                try:
                    with db.begin_nested():
                        db.add(
                            Accepted(
                                dataset_id=dataset.id,
                                run_id=run.id,
                                row_number=row.number,
                                business_key=key,
                                values=normalized,
                                quarantine_id=q.id if q else None,
                            )
                        )
                        db.flush()
                except IntegrityError:
                    failures = [
                        issue(
                            "unique_key",
                            ", ".join(rules["unique_keys"]),
                            "A valid record with this key already exists in this dataset",
                        )
                    ]
            if failures:
                run.rejected += 1
                for failure in failures:
                    counts[failure["rule"]] = counts.get(failure["rule"], 0) + 1
                if q:
                    row.outcome = "rejected"
                    row.failures = failures
                    q.status = "replay_failed"
                    audit(
                        db,
                        dataset,
                        "replay.rejected",
                        run.id,
                        quarantine_id=q.id,
                        failures=failures,
                    )
                else:
                    db.add(
                        Quarantine(
                            dataset_id=dataset.id,
                            run_id=run.id,
                            configuration_id=run.configuration_id,
                            row_number=row.number,
                            original=row.values,
                            failures=failures,
                        )
                    )
            else:
                run.accepted += 1
                if q:
                    q.status = "replayed"
                    row.outcome = "accepted"
                    row.failures = []
                    audit(db, dataset, "replay.accepted", run.id, quarantine_id=q.id)
            run.processed = row.number
        run.failures = counts
        run.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        if failpoint:
            failpoint(db, run)
        if run.processed >= run.total:
            rate = run.rejected / run.total if run.total else 0
            if rate > rules["max_failure_rate"]:
                run.state = "failed"
                run.error_kind = "validation"
                run.error = f"Failure rate {rate:.1%} exceeds {rules['max_failure_rate']:.1%}; accepted evidence is retained"
            else:
                run.state = "completed_with_errors" if run.rejected else "completed"
            run.finished_at = now()
            run.lease_token = None
            run.lease_until = None
            audit(
                db,
                dataset,
                "run.finished",
                run.id,
                state=run.state,
                accepted=run.accepted,
                rejected=run.rejected,
            )
            return False
        return True


def process(run_id, after_batch=None):
    token = claim(run_id)
    if not token:
        return
    while True:
        more = batch(run_id, token)
        log.info("batch committed", extra={"run_id": run_id})
        if after_batch:
            after_batch(run_id)
        if not more:
            return
        time.sleep(float(os.getenv("BATCH_DELAY", "0")))


def transient_failure(run_id, token=None):
    # The current lease is allowed to expire; beat republishes from PostgreSQL.
    with Session.begin() as db:
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run and run.state == "running":
            dataset = db.get(Dataset, run.dataset_id)
            run.error = "Transient processing error; waiting for bounded recovery"
            run.error_kind = "infrastructure"
            audit(db, dataset, "run.transient_failure", run.id)


def recoverable_ids():
    with Session() as db:
        return list(
            db.scalars(
                select(Run.id).where(
                    Run.state.in_(["queued", "running"]),
                    (Run.lease_until.is_(None)) | (Run.lease_until < now()),
                )
            )
        )

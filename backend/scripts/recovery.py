"""Hard-kill a processing subprocess after a real committed batch; recover by lease."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from sqlalchemy import select, func
from app.db import Session, engine
from app.models import User, Run, Accepted, Configuration, Audit, now
from app.seed import sales_rows, csv_bytes
from app.ingestion import parse_csv, persist
from app.processing import process


def demonstrate(n=2000):
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == "demo@dataguard.local"))
        if not user:
            raise RuntimeError("Seed demo first")
        content = csv_bytes(sales_rows(n))
        columns, rows = parse_csv(content)
        dataset = persist(
            db,
            user,
            "Synthetic crash-recovery proof",
            "recovery:synthetic",
            content,
            columns,
            rows,
            {"synthetic": True, "seed": 42},
        )
        db.flush()
        config = db.scalar(
            select(Configuration).where(Configuration.dataset_id == dataset.id)
        )
        run = Run(dataset_id=dataset.id, configuration_id=config.id, total=n)
        db.add(run)
        db.flush()
        run_id = run.id
        dataset_id = dataset.id
    child = subprocess.Popen(
        [sys.executable, "scripts/crash_child.py", run_id],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        if child.stdout.readline().strip() != "CHECKPOINT_COMMITTED":
            raise RuntimeError("Child did not commit a checkpoint")
        child.kill()
        child.wait(timeout=10)
        start = time.perf_counter()
        with Session() as db:
            checkpoint = db.get(Run, run_id).processed
        deadline = time.monotonic() + 60
        while True:
            with Session() as db:
                run = db.get(Run, run_id)
                expired = run.lease_until < now()
            if expired:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Lease did not expire within 60s")
            time.sleep(0.2)
        process(run_id)
        recovery_seconds = time.perf_counter() - start
        process(run_id)
        process(run_id)
        with Session() as db:
            run = db.get(Run, run_id)
            count = db.scalar(
                select(func.count())
                .select_from(Accepted)
                .where(Accepted.dataset_id == dataset_id)
            )
            events = db.scalars(
                select(Audit.action).where(Audit.run_id == run_id)
            ).all()
        assert (
            count == n
            and run.processed == n
            and run.accepted == n
            and "run.recovered" in events
        )
        return {
            "database": engine.dialect.name,
            "rows": n,
            "checkpoint_before_kill": checkpoint,
            "accepted_after_recovery": count,
            "duplicate_write_count": count - n,
            "recovery_seconds_including_lease_expiry": recovery_seconds,
            "attempts": run.attempts,
            "crash_method": "OS hard-kill of production processing subprocess, not Celery broker",
            "run_id": run_id,
            "audit_events": events,
        }
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=2000)
    parser.add_argument("--output", default="../docs/recovery-results.json")
    args = parser.parse_args()
    result = demonstrate(args.rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)

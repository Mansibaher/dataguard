"""Real measurements, isolated fresh dataset per run; preserves results in JSON."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import os
import platform
import sys
import time
import tracemalloc
from pathlib import Path
from sqlalchemy import select, func
from app.db import Session, engine
from app.models import User, Run, Accepted, Quarantine
from app.seed import sales_rows, csv_bytes
from app.ingestion import parse_csv, persist
from app.processing import process


def benchmark(n):
    content = csv_bytes(sales_rows(n, True))
    start = time.perf_counter()
    tracemalloc.start()
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == "demo@dataguard.local"))
        if not user:
            raise RuntimeError("Run seed first")
        columns, rows = parse_csv(content)
        dataset = persist(
            db,
            user,
            f"Synthetic benchmark · {n}",
            "benchmark:synthetic",
            content,
            columns,
            rows,
            {"synthetic": True, "seed": 42},
        )
        from app.models import Configuration

        db.flush()
        config = db.scalar(
            select(Configuration).where(Configuration.dataset_id == dataset.id)
        )
        run = Run(dataset_id=dataset.id, configuration_id=config.id, total=n)
        db.add(run)
        db.flush()
        run_id = run.id
        dataset_id = dataset.id
    del rows, columns, content
    processing_start = time.perf_counter()
    process(run_id)
    seconds = time.perf_counter() - processing_start
    with Session() as db:
        run = db.get(Run, run_id)
        a = db.scalar(
            select(func.count())
            .select_from(Accepted)
            .where(Accepted.dataset_id == dataset_id)
        )
        q = db.scalar(
            select(func.count())
            .select_from(Quarantine)
            .where(Quarantine.dataset_id == dataset_id)
        )
    process(run_id)
    process(run_id)
    with Session() as db:
        after = db.scalar(
            select(func.count())
            .select_from(Accepted)
            .where(Accepted.dataset_id == dataset_id)
        )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (a, q) == (n - 4, 4) and after == a and run.processed == n
    return {
        "rows": n,
        "dataset_id": dataset_id,
        "run_id": run_id,
        "processing_seconds": seconds,
        "end_to_end_seconds": time.perf_counter() - start,
        "rows_per_second": n / seconds,
        "peak_python_allocated_bytes": peak,
        "memory_method": "tracemalloc; Python allocations including ingestion, not total RSS; instrumentation enabled",
        "accepted": a,
        "quarantined": q,
        "expected_accepted": n - 4,
        "expected_quarantined": 4,
        "duplicate_writes_after_2_redeliveries": after - a,
        "state": run.state,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, nargs="+", default=[10000, 100000])
    parser.add_argument("--output", default="../docs/benchmark-results.json")
    args = parser.parse_args()
    report = {
        "environment": {
            "os": platform.platform(),
            "python": sys.version,
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "database": engine.dialect.name,
            "batch_size": os.getenv("BATCH_SIZE", "250"),
            "delivery": "direct call to production processing function; broker excluded",
        },
        "results": [],
    }
    for n in args.rows:
        report["results"].append(benchmark(n))
        print(json.dumps(report["results"][-1]), flush=True)
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))

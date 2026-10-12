import argparse
import csv
import io
import os
from sqlalchemy import select, delete
from .db import Session
from .models import (
    User,
    Dataset,
    Audit,
    ReplayItem,
    Accepted,
    Quarantine,
    Run,
    Configuration,
    InputRow,
)
from .auth import passwords
from .ingestion import parse_csv, persist


def sales_rows(n=40, dirty=False):
    import random

    rng = random.Random(42)
    rows = []
    for i in range(n):
        rows.append(
            {
                "transaction_id": f"TXN-{i + 1:06d}",
                "customer_id": f"CUS-{rng.randrange(100, 999)}",
                "transaction_date": f"2026-09-{i % 28 + 1:02d}",
                "amount": str(round(rng.uniform(20, 1500), 2)),
                "currency": "USD",
                "region": ["North", "South", "East", "West"][i % 4],
            }
        )
    if dirty and n >= 8:
        rows[1]["customer_id"] = ""
        rows[3]["amount"] = "-50"
        rows[5]["amount"] = "not-a-number"
        rows[7]["transaction_id"] = rows[0]["transaction_id"]
    return rows


def csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def seed(reset=False):
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == "demo@dataguard.local"))
        if not user:
            user = User(
                email="demo@dataguard.local",
                password=passwords.hash(os.getenv("DEMO_PASSWORD", "dataguard-demo")),
            )
            db.add(user)
            db.flush()
        if reset:
            ds = list(db.scalars(select(Dataset.id).where(Dataset.owner_id == user.id)))
            runs = list(db.scalars(select(Run.id).where(Run.dataset_id.in_(ds))))
            if db.scalar(
                select(Run.id).where(
                    Run.id.in_(runs), Run.state.in_(["running", "queued"])
                )
            ):
                raise RuntimeError("Cancel or finish demo jobs before reset")
            for table, predicate in [
                (Audit, Audit.owner_id == user.id),
                (ReplayItem, ReplayItem.run_id.in_(runs)),
                (Accepted, Accepted.dataset_id.in_(ds)),
                (Quarantine, Quarantine.dataset_id.in_(ds)),
                (Run, Run.dataset_id.in_(ds)),
                (Configuration, Configuration.dataset_id.in_(ds)),
                (InputRow, InputRow.dataset_id.in_(ds)),
                (Dataset, Dataset.id.in_(ds)),
            ]:
                db.execute(delete(table).where(predicate))
        if not db.scalar(select(Dataset.id).where(Dataset.owner_id == user.id)):
            for name, dirty in [
                ("Synthetic sales · clean", False),
                ("Synthetic sales · investigation", True),
            ]:
                content = csv_bytes(sales_rows(40, dirty))
                columns, rows = parse_csv(content)
                persist(
                    db,
                    user,
                    name,
                    "seed:synthetic",
                    content,
                    columns,
                    rows,
                    {"format": "csv", "synthetic": True, "seed": 42},
                )
    print("Local demo account seeded: demo@dataguard.local")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-demo-data", action="store_true")
    args = parser.parse_args()
    seed(args.reset_demo_data)

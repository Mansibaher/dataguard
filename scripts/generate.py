"""Generate fixed-seed synthetic sales datasets. Run from the repository root."""

import argparse
import csv
import random
from pathlib import Path

COLUMNS = [
    "transaction_id",
    "customer_id",
    "transaction_date",
    "amount",
    "currency",
    "region",
]


def generate(path, n, variant):
    rng = random.Random(42)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = (
        [c for c in COLUMNS if c != "customer_id"]
        if variant == "schema"
        else list(COLUMNS)
    )
    if variant in ("schema", "demo"):
        cols.append("campaign")
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=cols)
        writer.writeheader()
        for i in range(n):
            row = {
                "transaction_id": f"TXN-{i + 1:06d}",
                "customer_id": f"CUS-{rng.randrange(100, 999)}",
                "transaction_date": f"2026-09-{i % 28 + 1:02d}",
                "amount": str(round(rng.uniform(20, 1500), 2)),
                "currency": "USD",
                "region": ["North", "South", "East", "West"][i % 4],
            }
            if variant in ("dirty", "demo"):
                if i % 20 == 1:
                    row["customer_id"] = ""
                if i % 20 == 3:
                    row["amount"] = "-50"
                if i % 20 == 5:
                    row["amount"] = "oops"
            if variant in ("duplicates", "demo") and i % 20 == 7:
                row["transaction_id"] = f"TXN-{i - 6:06d}"
            if variant == "schema":
                row.pop("customer_id")
            if "campaign" in cols:
                row["campaign"] = "synthetic-fall"
            writer.writerow(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=40)
    parser.add_argument(
        "--variant",
        choices=["clean", "dirty", "duplicates", "schema", "demo"],
        default="demo",
    )
    parser.add_argument("--output", default="demo-data/synthetic-demo.csv")
    args = parser.parse_args()
    generate(args.output, args.rows, args.variant)

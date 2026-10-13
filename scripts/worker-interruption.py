"""Docker integration demo: kill Celery worker, restart, assert durable recovery."""

import os
import argparse
import json
import subprocess
import time
from pathlib import Path
import httpx
from generate import generate

parser = argparse.ArgumentParser()
parser.add_argument("--api", default="http://localhost:8001")
args = parser.parse_args()
client = httpx.Client(base_url=args.api, timeout=30)
token = (
    client.post(
        "/auth/token",
        data={
            "username": "demo@dataguard.local",
            "password": os.getenv("DEMO_PASSWORD", "dataguard-demo"),
        },
    )
    .raise_for_status()
    .json()["access_token"]
)
client.headers["Authorization"] = "Bearer " + token
file = Path("demo-data/synthetic-recovery.csv")
generate(file, 100000, "clean")
with file.open("rb") as handle:
    dataset = (
        client.post("/datasets/upload", files={"file": (file.name, handle, "text/csv")})
        .raise_for_status()
        .json()
    )
config = (
    client.get("/datasets/" + dataset["id"])
    .raise_for_status()
    .json()["configurations"][0]
)
run = (
    client.post(
        "/datasets/" + dataset["id"] + "/runs", json={"configuration_id": config["id"]}
    )
    .raise_for_status()
    .json()
)
deadline = time.monotonic() + 120
while True:
    status = client.get("/runs/" + run["id"]).raise_for_status().json()
    if 0 < status["processed"] < status["total"]:
        break
    if time.monotonic() > deadline or status["finished_at"]:
        raise RuntimeError(
            "No partial checkpoint observed; set BATCH_DELAY=0.1 and recreate worker"
        )
    time.sleep(0.1)
subprocess.run(["docker", "compose", "kill", "-s", "KILL", "worker"], check=True)
start = time.monotonic()
subprocess.run(["docker", "compose", "up", "-d", "worker"], check=True)
deadline = time.monotonic() + 300
while True:
    result = client.get("/runs/" + run["id"]).raise_for_status().json()
    if result["state"] == "completed":
        break
    if result["state"] in ("failed", "cancelled") or time.monotonic() > deadline:
        raise RuntimeError("Worker did not recover: " + str(result))
    time.sleep(1)
count = (
    client.get("/records", params={"dataset_id": dataset["id"]})
    .raise_for_status()
    .json()["total"]
)
assert (
    result["processed"] == 100000 and result["accepted"] == 100000 and count == 100000
)
output = {
    "rows": 100000,
    "accepted": count,
    "duplicate_write_count": count - 100000,
    "checkpoint_before_interruption": status["processed"],
    "recovery_seconds": time.monotonic() - start,
    "attempts": result["attempts"],
    "method": "Celery worker SIGKILL + Redis + PostgreSQL + scheduler",
}
Path("docs/celery-recovery-results.json").write_text(json.dumps(output, indent=2))
print(json.dumps(output))

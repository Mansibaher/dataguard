"""Portable DB polling runner for local development without a Redis daemon.
Production Compose uses Celery plus beat. This runner executes the same transactional core.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.processing import process, recoverable_ids

while True:
    for run_id in recoverable_ids():
        process(run_id)
    time.sleep(1)

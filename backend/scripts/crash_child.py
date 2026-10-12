"""Run production processing until parent terminates this actual process."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from app.processing import process


def hold_after_first_commit(run_id):
    print("CHECKPOINT_COMMITTED", flush=True)
    time.sleep(60)


process(sys.argv[1], after_batch=hold_after_first_commit)

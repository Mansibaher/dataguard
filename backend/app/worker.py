import json
import logging
import os
from celery import Celery
from sqlalchemy.exc import OperationalError
from .processing import process, recoverable_ids, transient_failure


class Formatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "run_id": getattr(record, "run_id", None),
            }
        )


handler = logging.StreamHandler()
handler.setFormatter(Formatter())
logging.getLogger("dataguard").addHandler(handler)
logging.getLogger("dataguard").setLevel(logging.INFO)
celery = Celery("dataguard", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 60},
    beat_schedule={
        "recover-durable-runs": {"task": "app.worker.scan", "schedule": 5.0}
    },
)


@celery.task(name="app.worker.execute", bind=True, max_retries=4)
def execute(self, run_id):
    try:
        process(run_id)
    except (OperationalError, ConnectionError, TimeoutError, OSError) as exc:
        try:
            transient_failure(run_id)
        except OperationalError:
            pass
        raise self.retry(exc=exc, countdown=min(2**self.request.retries * 2, 30))
    except Exception:
        # Unexpected code failures are bounded by the lease-attempt budget, with evidence in logs.
        logging.getLogger("dataguard").exception(
            "processing failed", extra={"run_id": run_id}
        )
        transient_failure(run_id)


@celery.task(name="app.worker.scan")
def scan():
    for run_id in recoverable_ids():
        execute.delay(run_id)


def enqueue(run_id):
    try:
        execute.apply_async(args=[run_id], retry=False)
    except Exception:
        logging.getLogger("dataguard").warning(
            "broker unavailable; durable scanner will republish",
            extra={"run_id": run_id},
        )

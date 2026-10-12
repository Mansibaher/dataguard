import os
from datetime import datetime
from typing import Any
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session as DB
from .db import session
from .models import (
    User,
    Dataset,
    Configuration,
    Run,
    InputRow,
    Quarantine,
    ReplayItem,
    Accepted,
    Audit,
    audit,
    now,
)
from .auth import current_user, passwords, token
from .validation import Rules, validate, business_key, dataset_issues
from .ingestion import parse_csv, persist, fetch_connector, MAX_BYTES
from .worker import enqueue

DUMMY_HASH = passwords.hash("not-a-login-password")
app = FastAPI(title="DataGuard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


def owned(db, user, dataset_id, lock=False):
    query = select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    dataset = db.scalar(query.with_for_update() if lock else query)
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    return dataset


def owned_run(db, user, run_id, lock=False):
    query = select(Run).where(Run.id == run_id)
    run = db.scalar(query.with_for_update() if lock else query)
    if not run:
        raise HTTPException(404, "Run not found")
    owned(db, user, run.dataset_id)
    return run


def owned_quarantine(db, user, q_id, lock=False):
    query = select(Quarantine).where(Quarantine.id == q_id)
    q = db.scalar(query.with_for_update() if lock else query)
    if not q:
        raise HTTPException(404, "Record not found")
    owned(db, user, q.dataset_id)
    return q


def summary(dataset):
    return {
        k: getattr(dataset, k)
        for k in [
            "id",
            "name",
            "source",
            "provenance",
            "content_hash",
            "columns",
            "row_count",
            "created_at",
        ]
    }


def run_data(run):
    data = {
        k: getattr(run, k)
        for k in [
            "id",
            "dataset_id",
            "configuration_id",
            "kind",
            "state",
            "total",
            "processed",
            "accepted",
            "rejected",
            "failures",
            "warnings",
            "error",
            "error_kind",
            "attempts",
            "created_at",
            "started_at",
            "finished_at",
            "lease_until",
        ]
    }
    end = run.finished_at or now()
    seconds = max(0, (end - run.started_at).total_seconds()) if run.started_at else 0
    data.update(
        duration_seconds=round(seconds, 3),
        rows_per_second=round(run.processed / seconds, 2) if seconds else 0,
    )
    return data


def page_result(db, query, page, size, serialize):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            serialize(x)
            for x in db.scalars(query.offset((page - 1) * size).limit(size))
        ],
    }


@app.get("/health")
def health(db: DB = Depends(session)):
    db.execute(select(1))
    return {"status": "ok"}


@app.post("/auth/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: DB = Depends(session)):
    user = db.scalar(select(User).where(User.email == form.username))
    # Perform a hash check even for an unknown email.
    valid = passwords.verify(form.password, user.password if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": token(user), "token_type": "bearer"}


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "local_demo": user.email == "demo@dataguard.local",
    }


@app.get("/datasets")
def datasets(
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    user=Depends(current_user),
    db: DB = Depends(session),
):
    return page_result(
        db,
        select(Dataset)
        .where(Dataset.owner_id == user.id)
        .order_by(Dataset.created_at.desc()),
        page,
        size,
        summary,
    )


@app.post("/datasets/upload", status_code=201)
async def upload(
    file: UploadFile = File(), user=Depends(current_user), db: DB = Depends(session)
):
    content = await file.read(MAX_BYTES + 1)
    try:
        columns, rows = parse_csv(content)
        dataset = persist(
            db, user, file.filename or "Uploaded dataset", "csv", content, columns, rows
        )
        db.commit()
        return summary(dataset)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/sources")
def sources(user=Depends(current_user)):
    import json

    return {
        "items": list(
            json.loads(
                os.getenv(
                    "CONNECTOR_SOURCES", '{"demo":"http://mock-source:8090/sales"}'
                )
            ).keys()
        )
    }


class ConnectorRequest(BaseModel):
    source: str = Field(default="demo", max_length=100)
    page_size: int = Field(default=100, ge=1, le=1000)
    max_pages: int = Field(default=10, ge=1, le=100)


@app.post("/datasets/connector", status_code=201)
def connector(
    body: ConnectorRequest, user=Depends(current_user), db: DB = Depends(session)
):
    try:
        content, columns, rows, provenance = fetch_connector(
            body.source, body.page_size, body.max_pages
        )
        dataset = persist(
            db,
            user,
            "HTTP sales · " + body.source,
            "http:" + body.source,
            content,
            columns,
            rows,
            provenance,
        )
        db.commit()
        return summary(dataset)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/datasets/{dataset_id}")
def dataset_detail(
    dataset_id: str, user=Depends(current_user), db: DB = Depends(session)
):
    dataset = owned(db, user, dataset_id)
    configs = db.scalars(
        select(Configuration)
        .where(Configuration.dataset_id == dataset.id)
        .order_by(Configuration.version.desc())
    ).all()
    return {
        **summary(dataset),
        "configurations": [
            {
                "id": c.id,
                "version": c.version,
                "rules": c.rules,
                "created_at": c.created_at,
            }
            for c in configs
        ],
    }


@app.get("/datasets/{dataset_id}/preview")
def preview(
    dataset_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    user=Depends(current_user),
    db: DB = Depends(session),
):
    owned(db, user, dataset_id)
    return page_result(
        db,
        select(InputRow)
        .where(InputRow.dataset_id == dataset_id)
        .order_by(InputRow.number),
        page,
        size,
        lambda r: {"number": r.number, "values": r.values},
    )


@app.get("/datasets/{dataset_id}/original")
def original(dataset_id: str, user=Depends(current_user), db: DB = Depends(session)):
    dataset = owned(db, user, dataset_id)
    return Response(
        dataset.original,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="original-input"'},
    )


@app.post("/datasets/{dataset_id}/configurations", status_code=201)
def configure(
    dataset_id: str, body: Rules, user=Depends(current_user), db: DB = Depends(session)
):
    dataset = owned(db, user, dataset_id, True)
    previous = db.scalar(
        select(Configuration)
        .where(Configuration.dataset_id == dataset_id)
        .order_by(Configuration.version.desc())
    )
    new = body.model_dump()
    if previous:
        old = previous.rules
        keys = new["unique_keys"]
        if keys != old["unique_keys"] or [
            (c["name"], c["type"], c["date_format"])
            for c in new["columns"]
            if c["name"] in keys
        ] != [
            (c["name"], c["type"], c["date_format"])
            for c in old["columns"]
            if c["name"] in keys
        ]:
            raise HTTPException(
                422,
                "Unique-key definition is fixed for this dataset; ingest a new dataset to change it",
            )
    config = Configuration(
        dataset_id=dataset_id,
        version=previous.version + 1 if previous else 1,
        rules=new,
    )
    db.add(config)
    db.flush()
    audit(db, dataset, "configuration.created", version=config.version)
    db.commit()
    return {"id": config.id, "version": config.version, "rules": config.rules}


class StartRequest(BaseModel):
    configuration_id: str


@app.post("/datasets/{dataset_id}/runs", status_code=201)
def start(
    dataset_id: str,
    body: StartRequest,
    user=Depends(current_user),
    db: DB = Depends(session),
):
    dataset = owned(db, user, dataset_id)
    config = db.get(Configuration, body.configuration_id)
    if not config or config.dataset_id != dataset_id:
        raise HTTPException(404, "Configuration not found")
    run = Run(
        dataset_id=dataset_id, configuration_id=config.id, total=dataset.row_count
    )
    db.add(run)
    db.flush()
    audit(db, dataset, "run.queued", run.id, configuration_version=config.version)
    db.commit()
    enqueue(run.id)
    return run_data(run)


@app.get("/runs")
def runs(
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    dataset_id: str | None = None,
    user=Depends(current_user),
    db: DB = Depends(session),
):
    query = select(Run).join(Dataset).where(Dataset.owner_id == user.id)
    if dataset_id:
        query = query.where(Run.dataset_id == dataset_id)
    return page_result(db, query.order_by(Run.created_at.desc()), page, size, run_data)


@app.get("/runs/{run_id}")
def run_detail(run_id: str, user=Depends(current_user), db: DB = Depends(session)):
    run = owned_run(db, user, run_id)
    config = db.get(Configuration, run.configuration_id)
    outcomes = (
        db.scalars(
            select(ReplayItem)
            .where(ReplayItem.run_id == run_id)
            .order_by(ReplayItem.number)
            .limit(1000)
        ).all()
        if run.kind == "replay"
        else []
    )
    return {
        **run_data(run),
        "configuration": {
            "id": config.id,
            "version": config.version,
            "rules": config.rules,
        },
        "replay_outcomes": [
            {
                "quarantine_id": r.quarantine_id,
                "outcome": r.outcome,
                "failures": r.failures,
            }
            for r in outcomes
        ],
    }


@app.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user=Depends(current_user), db: DB = Depends(session)):
    run = owned_run(db, user, run_id, True)
    if run.state not in ("queued", "running"):
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    run.state = "cancelled"
    run.finished_at = now()
    run.lease_token = None
    run.lease_until = None

    if run.kind == "replay":
        for item in db.scalars(
            select(ReplayItem).where(
                ReplayItem.run_id == run.id, ReplayItem.outcome.is_(None)
            )
        ):
            db.get(Quarantine, item.quarantine_id).status = "corrected"
    audit(db, db.get(Dataset, run.dataset_id), "run.cancelled", run.id)
    db.commit()
    return run_data(run)


@app.post("/runs/{run_id}/recover")
def recover(run_id: str, user=Depends(current_user), db: DB = Depends(session)):
    run = owned_run(db, user, run_id, True)
    if run.state == "running" and run.lease_until and run.lease_until > now():
        raise HTTPException(
            409, "Worker still holds a live lease; wait for lease expiry"
        )
    if run.state not in ("queued", "running", "failed") or (
        run.state == "failed" and run.error_kind != "infrastructure"
    ):
        raise HTTPException(
            409,
            "Validation failures require a new run; terminal successes cannot be recovered",
        )
    run.state = "queued"
    run.lease_token = None
    run.lease_until = None
    run.attempts = 0
    run.error = None
    run.error_kind = None
    run.finished_at = None
    audit(
        db,
        db.get(Dataset, run.dataset_id),
        "run.manual_recovery",
        run.id,
        checkpoint=run.processed,
    )
    db.commit()
    enqueue(run.id)
    return run_data(run)


@app.get("/records")
def records(
    dataset_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    user=Depends(current_user),
    db: DB = Depends(session),
):
    query = select(Accepted).join(Dataset).where(Dataset.owner_id == user.id)
    if dataset_id:
        query = query.where(Accepted.dataset_id == dataset_id)
    return page_result(
        db,
        query.order_by(Accepted.created_at.desc()),
        page,
        size,
        lambda r: {
            "id": r.id,
            "dataset_id": r.dataset_id,
            "run_id": r.run_id,
            "row_number": r.row_number,
            "values": r.values,
            "quarantine_id": r.quarantine_id,
            "created_at": r.created_at,
        },
    )


def quarantine_data(q):
    return {
        k: getattr(q, k)
        for k in [
            "id",
            "dataset_id",
            "run_id",
            "configuration_id",
            "row_number",
            "original",
            "corrected",
            "failures",
            "status",
            "created_at",
        ]
    }


@app.get("/quarantine")
def quarantine(
    dataset_id: str | None = None,
    reason: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    user=Depends(current_user),
    db: DB = Depends(session),
):
    query = select(Quarantine).join(Dataset).where(Dataset.owner_id == user.id)
    if dataset_id:
        query = query.where(Quarantine.dataset_id == dataset_id)
    # Portable failure-code matching on the serialized JSON; codes are validated against exact allowed names.
    if reason:
        if reason not in [
            "non_null",
            "type",
            "minimum",
            "maximum",
            "allowed",
            "unique_key",
        ]:
            raise HTTPException(422, "Unknown failure reason")
        from sqlalchemy import cast, String

        query = query.where(
            cast(Quarantine.failures, String).like('%"rule": "' + reason + '"%')
        )
    return page_result(
        db, query.order_by(Quarantine.created_at.desc()), page, size, quarantine_data
    )


class Correction(BaseModel):
    values: dict[str, Any]


@app.put("/quarantine/{q_id}/correction")
def correct(
    q_id: str, body: Correction, user=Depends(current_user), db: DB = Depends(session)
):
    if len(body.values) > 100 or any(
        isinstance(v, (dict, list)) or len(str(v)) > 10000 for v in body.values.values()
    ):
        raise HTTPException(
            422,
            "Correction must contain at most 100 flat fields of at most 10,000 characters",
        )
    q = owned_quarantine(db, user, q_id, True)
    if q.status in ("replayed", "replay_queued"):
        raise HTTPException(409, "Replayed or queued records cannot be edited")
    config = db.get(Configuration, q.configuration_id)
    normalized, failures = validate(body.values, config.rules)
    schema_failures, _ = dataset_issues(list(body.values), config.rules)
    failures += schema_failures
    if not failures and db.scalar(
        select(Accepted.id).where(
            Accepted.dataset_id == q.dataset_id,
            Accepted.business_key == business_key(normalized, config.rules),
        )
    ):
        failures = [
            {
                "rule": "unique_key",
                "field": ",".join(config.rules["unique_keys"]),
                "message": "This key already exists; choose a distinct transaction ID",
            }
        ]
    if failures:
        return {"valid": False, "failures": failures}
    q.corrected = dict(body.values)
    q.status = "corrected"
    audit(
        db,
        db.get(Dataset, q.dataset_id),
        "quarantine.corrected",
        q.run_id,
        quarantine_id=q.id,
        values=body.values,
        configuration_version=config.version,
    )
    db.commit()
    return {"valid": True, "failures": [], "record": quarantine_data(q)}


class ReplayRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


@app.post("/quarantine/replay", status_code=201)
def replay(body: ReplayRequest, user=Depends(current_user), db: DB = Depends(session)):
    if len(set(body.ids)) != len(body.ids):
        raise HTTPException(422, "Select distinct quarantine records")
    qs = [owned_quarantine(db, user, i, True) for i in sorted(body.ids)]
    if (
        len({q.dataset_id for q in qs}) != 1
        or len({q.configuration_id for q in qs}) != 1
    ):
        raise HTTPException(
            422, "Replay one dataset and original configuration version at a time"
        )
    if any(
        q.status not in ("corrected", "replay_failed") or not q.corrected for q in qs
    ):
        raise HTTPException(409, "Every selected record needs a valid saved correction")
    run = Run(
        dataset_id=qs[0].dataset_id,
        configuration_id=qs[0].configuration_id,
        kind="replay",
        total=len(qs),
    )
    db.add(run)
    db.flush()
    for i, q in enumerate(qs, 1):
        q.status = "replay_queued"
        db.add(
            ReplayItem(
                run_id=run.id, quarantine_id=q.id, number=i, values=dict(q.corrected)
            )
        )
    audit(
        db,
        db.get(Dataset, run.dataset_id),
        "replay.queued",
        run.id,
        quarantine_ids=body.ids,
        configuration_id=run.configuration_id,
    )
    db.commit()
    enqueue(run.id)
    return run_data(run)


@app.get("/audit")
def history(
    dataset_id: str | None = None,
    run_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    user=Depends(current_user),
    db: DB = Depends(session),
):
    query = select(Audit).where(Audit.owner_id == user.id)
    if dataset_id:
        query = query.where(Audit.dataset_id == dataset_id)
    if run_id:
        query = query.where(Audit.run_id == run_id)
    return page_result(
        db,
        query.order_by(Audit.created_at.desc()),
        page,
        size,
        lambda a: {
            "id": a.id,
            "dataset_id": a.dataset_id,
            "run_id": a.run_id,
            "action": a.action,
            "detail": a.detail,
            "created_at": a.created_at,
        },
    )


@app.get("/overview")
def overview(user=Depends(current_user), db: DB = Depends(session)):
    ds = list(db.scalars(select(Dataset.id).where(Dataset.owner_id == user.id)))
    count = lambda entity: db.scalar(
        select(func.count()).select_from(entity).where(entity.dataset_id.in_(ds))
    )
    latest = db.scalars(
        select(Run)
        .where(Run.dataset_id.in_(ds))
        .order_by(Run.created_at.desc())
        .limit(20)
    ).all()
    failures = {}
    for run in latest:
        for rule, n in run.failures.items():
            failures[rule] = failures.get(rule, 0) + n
    return {
        "datasets": len(ds),
        "accepted": count(Accepted),
        "quarantined": count(Quarantine),
        "runs": count(Run),
        "active": sum(r.state in ("running", "queued") for r in latest),
        "recent_runs": [run_data(r) for r in latest],
        "failures": failures,
    }

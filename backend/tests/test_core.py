import copy
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from app.db import Session, engine
from app.models import (
    Run,
    Dataset,
    Quarantine,
    Accepted,
    Audit,
    Configuration,
    ReplayItem,
    now,
)
from app.processing import process, claim, batch, recoverable_ids
from app.validation import SALES, validate, Rules
from app.seed import sales_rows, csv_bytes
from app.ingestion import parse_csv, fetch_connector, MAX_BYTES
from app.auth import token
import httpx


def ingest(client, rows=None, content=None):
    response = client.post(
        "/datasets/upload",
        files={
            "file": (
                "sales.csv",
                content or csv_bytes(rows or sales_rows(8)),
                "text/csv",
            )
        },
    )
    assert response.status_code == 201, response.text
    ds = response.json()
    config = client.get("/datasets/" + ds["id"]).json()["configurations"][0]
    run = client.post(
        "/datasets/" + ds["id"] + "/runs", json={"configuration_id": config["id"]}
    ).json()
    return ds, run


def count(entity):
    with Session() as db:
        return db.scalar(select(func.count()).select_from(entity))


def test_valid_rows_and_repeated_delivery(client):
    ds, r = ingest(client)
    process(r["id"])
    process(r["id"])
    process(r["id"])
    result = client.get("/runs/" + r["id"]).json()
    assert result["state"] == "completed" and result["accepted"] == 8
    assert count(Accepted) == 8 and count(Quarantine) == 0


def test_actionable_failures_and_original_values(client):
    ds, r = ingest(client, sales_rows(40, True))
    process(r["id"])
    result = client.get("/runs/" + r["id"]).json()
    assert (result["accepted"], result["rejected"]) == (36, 4)
    qs = client.get("/quarantine").json()["items"]
    assert {f["rule"] for q in qs for f in q["failures"]} == {
        "non_null",
        "minimum",
        "type",
        "unique_key",
    }
    assert (
        next(q for q in qs if q["row_number"] == 6)["original"]["amount"]
        == "not-a-number"
    )
    assert all(q["configuration_id"] == r["configuration_id"] for q in qs)
    assert client.get("/quarantine?reason=type").json()["total"] == 1


def test_duplicate_scope_across_runs_and_datasets(client):
    ds, r = ingest(client)
    process(r["id"])
    r2 = client.post(
        "/datasets/" + ds["id"] + "/runs",
        json={"configuration_id": r["configuration_id"]},
    ).json()
    process(r2["id"])
    assert client.get("/runs/" + r2["id"]).json()["rejected"] == 8
    assert count(Accepted) == 8
    ds3, r3 = ingest(client)
    process(r3["id"])
    assert count(Accepted) == 16


def test_dataset_schema_failure_no_partial_writes(client):
    rows = sales_rows(8)
    for r in rows:
        del r["customer_id"]
    ds, r = ingest(client, rows)
    process(r["id"])
    process(r["id"])
    result = client.get("/runs/" + r["id"]).json()
    assert (
        result["state"] == "failed"
        and result["error_kind"] == "validation"
        and result["processed"] == 0
    )
    assert count(Accepted) == 0 and count(Quarantine) == 0
    assert client.post("/runs/" + r["id"] + "/recover").status_code == 409


def test_unexpected_column_warn_and_reject(client):
    rows = sales_rows(8)
    for row in rows:
        row["surprise"] = "evidence"
    ds, r = ingest(client, rows)
    process(r["id"])
    assert (
        client.get("/runs/" + r["id"]).json()["warnings"][0]["rule"]
        == "unexpected_column"
    )
    rules = copy.deepcopy(SALES)
    rules["unexpected"] = "reject"
    config = client.post("/datasets/" + ds["id"] + "/configurations", json=rules).json()
    r2 = client.post(
        "/datasets/" + ds["id"] + "/runs", json={"configuration_id": config["id"]}
    ).json()
    process(r2["id"])
    assert client.get("/runs/" + r2["id"]).json()["processed"] == 0


def test_failure_rate_retains_evidence(client):
    ds, r = ingest(client, sales_rows(8, True))
    process(r["id"])
    result = client.get("/runs/" + r["id"]).json()
    assert (
        result["state"] == "failed"
        and result["accepted"] == 4
        and result["rejected"] == 4
    )
    assert count(Accepted) == 4 and count(Quarantine) == 4


def test_partial_batch_rollback(client, monkeypatch):
    monkeypatch.setattr("app.processing.BATCH_SIZE", 3)
    ds, r = ingest(client)
    lease = claim(r["id"])

    def fail(db, run):
        raise RuntimeError("Injected failure before commit")

    with pytest.raises(RuntimeError):
        batch(r["id"], lease, fail)
    assert count(Accepted) == 0
    assert client.get("/runs/" + r["id"]).json()["processed"] == 0
    while batch(r["id"], lease):
        pass
    assert count(Accepted) == 8


def test_abandoned_lease_resume_and_fencing(client, monkeypatch):
    monkeypatch.setattr("app.processing.BATCH_SIZE", 3)
    ds, r = ingest(client)
    old = claim(r["id"])
    assert batch(r["id"], old)
    assert count(Accepted) == 3 and claim(r["id"]) is None
    with Session.begin() as db:
        db.get(Run, r["id"]).lease_until = now() - timedelta(seconds=1)
    assert r["id"] in recoverable_ids()
    new = claim(r["id"])
    assert new != old
    assert batch(r["id"], old) is False
    while batch(r["id"], new):
        pass
    assert count(Accepted) == 8
    assert client.get("/runs/" + r["id"]).json()["attempts"] == 2
    assert any(
        a["action"] == "run.recovered" for a in client.get("/audit").json()["items"]
    )


def test_cancel_fences_worker(client, monkeypatch):
    monkeypatch.setattr("app.processing.BATCH_SIZE", 3)
    ds, r = ingest(client)
    lease = claim(r["id"])
    batch(r["id"], lease)
    assert client.post("/runs/" + r["id"] + "/cancel").status_code == 200
    assert batch(r["id"], lease) is False and count(Accepted) == 3


def test_attempt_budget_is_bounded(client):
    ds, r = ingest(client)
    for i in range(5):
        assert claim(r["id"])
        with Session.begin() as db:
            db.get(Run, r["id"]).lease_until = now() - timedelta(seconds=1)
    assert claim(r["id"]) is None
    assert client.get("/runs/" + r["id"]).json()["state"] == "failed"
    assert client.post("/runs/" + r["id"] + "/recover").status_code == 200
    process(r["id"])
    assert count(Accepted) == 8


def test_correction_replay_preserves_evidence_and_audit(client):
    ds, r = ingest(client, sales_rows(40, True))
    process(r["id"])
    q = next(
        q for q in client.get("/quarantine").json()["items"] if q["row_number"] == 2
    )
    invalid = client.put(
        "/quarantine/" + q["id"] + "/correction", json={"values": q["original"]}
    ).json()
    assert not invalid["valid"]
    values = {**q["original"], "customer_id": "CUS-fixed"}
    assert client.put(
        "/quarantine/" + q["id"] + "/correction", json={"values": values}
    ).json()["valid"]
    replay = client.post("/quarantine/replay", json={"ids": [q["id"]]}).json()
    process(replay["id"])
    process(replay["id"])
    with Session() as db:
        stored = db.get(Quarantine, q["id"])
        assert (
            stored.original["customer_id"] == ""
            and stored.corrected["customer_id"] == "CUS-fixed"
            and stored.status == "replayed"
        )
        assert db.get(Run, replay["id"]).configuration_id == q["configuration_id"]
    assert count(Accepted) == 37
    actions = {a["action"] for a in client.get("/audit").json()["items"]}
    assert {"quarantine.corrected", "replay.queued", "replay.accepted"} <= actions
    assert (
        client.get("/runs/" + replay["id"]).json()["replay_outcomes"][0]["outcome"]
        == "accepted"
    )


def test_replay_snapshot_and_failed_outcome(client):
    ds, r = ingest(client, sales_rows(40, True))
    process(r["id"])
    qs = client.get("/quarantine").json()["items"]
    chosen = [q for q in qs if q["row_number"] in (2, 4)]
    for q in chosen:
        values = {
            **q["original"],
            "transaction_id": "NEW-ID",
            "customer_id": "CUS-fixed",
            "amount": "50",
        }
        assert client.put(
            "/quarantine/" + q["id"] + "/correction", json={"values": values}
        ).json()["valid"]
    replay = client.post(
        "/quarantine/replay", json={"ids": [q["id"] for q in chosen]}
    ).json()
    process(replay["id"])
    result = client.get("/runs/" + replay["id"]).json()
    assert (result["accepted"], result["rejected"]) == (1, 1)
    assert {o["outcome"] for o in result["replay_outcomes"]} == {"accepted", "rejected"}
    assert count(Quarantine) == 4


def test_ownership_and_file_isolation(client, users):
    ds, r = ingest(client, sales_rows(40, True))
    process(r["id"])
    q = client.get("/quarantine").json()["items"][0]
    client.headers["Authorization"] = "Bearer " + token(users[1])
    for route in [
        "/datasets/" + ds["id"],
        "/datasets/" + ds["id"] + "/preview",
        "/datasets/" + ds["id"] + "/original",
        "/runs/" + r["id"],
    ]:
        assert client.get(route).status_code == 404
    assert (
        client.post(
            "/datasets/" + ds["id"] + "/runs",
            json={"configuration_id": r["configuration_id"]},
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/quarantine/" + q["id"] + "/correction", json={"values": q["original"]}
        ).status_code
        == 404
    )
    assert client.post("/quarantine/replay", json={"ids": [q["id"]]}).status_code == 404
    for route in ["/datasets", "/runs", "/records", "/quarantine", "/audit"]:
        assert client.get(route).json()["total"] == 0


def test_authentication(client):
    client.headers.clear()
    assert client.get("/datasets").status_code == 401
    assert (
        client.post(
            "/auth/token", data={"username": "a@test.local", "password": "bad"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/token", data={"username": "a@test.local", "password": "password"}
        ).status_code
        == 200
    )


def test_configuration_version_reproducibility(client):
    ds, r = ingest(client)
    changed = copy.deepcopy(SALES)
    changed["columns"][3]["maximum"] = 1
    new = client.post("/datasets/" + ds["id"] + "/configurations", json=changed).json()
    assert new["version"] == 2
    process(r["id"])
    assert client.get("/runs/" + r["id"]).json()["accepted"] == 8
    assert (
        client.get("/runs/" + r["id"]).json()["configuration"]["rules"]["columns"][3][
            "maximum"
        ]
        == 1000000
    )
    changed["unique_keys"] = ["customer_id"]
    assert (
        client.post(
            "/datasets/" + ds["id"] + "/configurations", json=changed
        ).status_code
        == 422
    )


def test_csv_bom_malformed_limits_and_hash(client):
    data = b"\xef\xbb\xbf" + csv_bytes(sales_rows(8))
    ds, r = ingest(client, content=data)
    assert client.get("/datasets/" + ds["id"] + "/original").content == data
    import hashlib

    assert ds["content_hash"] == hashlib.sha256(data).hexdigest()
    for bad in [b"", b"a,a\n1,2", b"a,b\n1", b"\xff", b'a,b\n"broken', b"a\x00\n1"]:
        with pytest.raises(ValueError):
            parse_csv(bad)
    with pytest.raises(ValueError):
        parse_csv(b"x" * (MAX_BYTES + 1))


def test_strict_normalization():
    row = sales_rows(1)[0]
    row["amount"] = "NaN"
    normalized, errors = validate(row, SALES)
    assert errors[0]["rule"] == "type"
    row["amount"] = "1,000"
    assert validate(row, SALES)[1]
    row["amount"] = " 20.10 "
    row["customer_id"] = "  CUS-1  "
    values, errors = validate(row, SALES)
    assert (
        not errors and values["amount"] == "20.10" and values["customer_id"] == "CUS-1"
    )
    row["transaction_date"] = "2026-99-01"
    assert validate(row, SALES)[1]


def test_connector_pagination_and_bounded_retries():
    calls = []
    delays = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("test")
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"rows": sales_rows(1), "has_more": page < 2})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        content, columns, rows, provenance = fetch_connector(
            "demo", client=client, sleep=delays.append
        )
    assert len(rows) == 2 and len(calls) == 3 and delays == [0.25]
    attempts = []

    def unavailable(request):
        attempts.append(1)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        with pytest.raises(ValueError, match="3 attempts"):
            fetch_connector("demo", client=client, sleep=lambda _: None)
    assert len(attempts) == 3


def test_connector_permanent_failure_and_ssrf():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="permanent"):
            fetch_connector("demo", client=client)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="allowed"):
        fetch_connector("http://localhost/admin")


@pytest.mark.postgres
@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Real PostgreSQL required for locks"
)
def test_concurrent_delivery_postgres(client):
    from concurrent.futures import ThreadPoolExecutor

    ds, r = ingest(client, sales_rows(80))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(process, [r["id"]] * 4))
    assert (
        count(Accepted) == 80
        and client.get("/runs/" + r["id"]).json()["accepted"] == 80
    )


def test_cancelled_replay_restores_pending_corrections(client):
    ds, r = ingest(client, sales_rows(40, True))
    process(r["id"])
    q = next(
        q for q in client.get("/quarantine").json()["items"] if q["row_number"] == 2
    )
    values = {**q["original"], "customer_id": "CUS-restored"}
    assert client.put(
        "/quarantine/" + q["id"] + "/correction", json={"values": values}
    ).json()["valid"]
    replay = client.post("/quarantine/replay", json={"ids": [q["id"]]}).json()
    assert (
        client.put(
            "/quarantine/" + q["id"] + "/correction", json={"values": values}
        ).status_code
        == 409
    )
    assert client.post("/quarantine/replay", json={"ids": [q["id"]]}).status_code == 409
    assert client.post("/runs/" + replay["id"] + "/cancel").status_code == 200
    with Session() as db:
        assert db.get(Quarantine, q["id"]).status == "corrected"
    again = client.post("/quarantine/replay", json={"ids": [q["id"]]}).json()
    process(again["id"])
    assert count(Accepted) == 37


def test_connector_limit_and_permanent_json_errors():
    calls = []

    def malformed(request):
        calls.append(1)
        return httpx.Response(200, content=b"not-json")

    with httpx.Client(transport=httpx.MockTransport(malformed)) as client:
        with pytest.raises(ValueError, match="malformed"):
            fetch_connector("demo", client=client)
    assert len(calls) == 1

    def endless(request):
        return httpx.Response(200, json={"rows": sales_rows(1), "has_more": True})

    with httpx.Client(transport=httpx.MockTransport(endless)) as client:
        with pytest.raises(ValueError, match="page limit"):
            fetch_connector("demo", max_pages=2, client=client)


def test_csv_row_cap_and_range_configuration(monkeypatch):
    monkeypatch.setattr("app.ingestion.MAX_ROWS", 2)
    with pytest.raises(ValueError, match="row"):
        parse_csv(csv_bytes(sales_rows(3)))
    invalid = copy.deepcopy(SALES)
    invalid["columns"][3]["minimum"] = 10
    invalid["columns"][3]["maximum"] = 1
    with pytest.raises(ValueError, match="Minimum"):
        Rules.model_validate(invalid)

import csv
import hashlib
import io
import json
import os
import time
from urllib.parse import urlparse
import httpx
from .models import Dataset, InputRow, Configuration, audit
from .validation import SALES

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100000


def parse_csv(content):
    if len(content) > MAX_BYTES:
        raise ValueError("CSV exceeds the 10 MiB limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Save the CSV as UTF-8 or UTF-8 with BOM")
    if "\x00" in text:
        raise ValueError("NUL bytes are not valid CSV text")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        columns = next(reader)
        if not columns or any(not c.strip() for c in columns):
            raise ValueError("Every column needs a header")
        if len(columns) > 100:
            raise ValueError("At most 100 columns are supported")
        if len(set(columns)) != len(columns):
            raise ValueError("Duplicate column headers are ambiguous")
        rows = []
        for number, row in enumerate(reader, 1):
            if number > MAX_ROWS:
                raise ValueError("CSV exceeds the 100,000-row limit")
            if len(row) != len(columns):
                raise ValueError(
                    f"CSV record {number + 1}: expected {len(columns)} values, got {len(row)}"
                )
            rows.append(dict(zip(columns, row)))
        if not rows:
            raise ValueError("CSV needs at least one data row")
        return columns, rows
    except StopIteration:
        raise ValueError("CSV is empty")
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV: {exc}")


def persist(db, owner, name, source, content, columns, rows, provenance=None):
    dataset = Dataset(
        owner_id=owner.id,
        name=name[:200],
        source=source,
        provenance=provenance or {"format": "csv", "synthetic": False},
        content_hash=hashlib.sha256(content).hexdigest(),
        original=content,
        columns=columns,
        row_count=len(rows),
    )
    db.add(dataset)
    db.flush()
    # Bulk insert bounded groups, all within the ingestion transaction.
    from sqlalchemy import insert

    for offset in range(0, len(rows), 1000):
        db.execute(
            insert(InputRow),
            [
                {"dataset_id": dataset.id, "number": offset + i + 1, "values": row}
                for i, row in enumerate(rows[offset : offset + 1000])
            ],
        )
    db.add(Configuration(dataset_id=dataset.id, version=1, rules=SALES))
    audit(
        db,
        dataset,
        "dataset.ingested",
        rows=len(rows),
        sha256=dataset.content_hash,
        source=source,
    )
    return dataset


def connector_source(source):
    # Select an exact administrator-configured endpoint, never a user URL.
    sources = json.loads(
        os.getenv("CONNECTOR_SOURCES", '{"demo":"http://mock-source:8090/sales"}')
    )
    if source not in sources:
        raise ValueError("Select an allowed connector source")
    url = sources[source]
    if urlparse(url).scheme not in ("http", "https") or urlparse(url).username:
        raise ValueError("Invalid administrator connector configuration")
    return url


def fetch_connector(source, page_size=100, max_pages=10, client=None, sleep=time.sleep):
    url = connector_source(source)
    own = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(5.0), follow_redirects=False, trust_env=False
    )
    all_rows = []
    attempts = 0
    response_bytes = 0
    try:
        for page in range(1, max_pages + 1):
            for attempt in range(3):
                attempts += 1
                try:
                    headers = {}
                    token = os.getenv("CONNECTOR_TOKEN")
                    if token:
                        headers["Authorization"] = "Bearer " + token
                    with client.stream(
                        "GET",
                        url,
                        params={"page": page, "size": page_size},
                        headers=headers,
                    ) as response:
                        if response.status_code >= 500 or response.status_code == 429:
                            raise httpx.TimeoutException("Transient source response")
                        if response.status_code != 200:
                            raise ValueError(
                                "Connector returned a permanent HTTP error"
                            )
                        parts = []
                        for chunk in response.iter_bytes():
                            response_bytes += len(chunk)
                            if response_bytes > MAX_BYTES:
                                raise ValueError("Connector exceeds the 10 MiB limit")
                            parts.append(chunk)
                        payload = json.loads(b"".join(parts))
                    break
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 2:
                        raise ValueError(
                            "Connector unavailable after 3 attempts on this page"
                        )
                    sleep(0.25 * 2**attempt)
            rows = payload.get("rows")
            if not isinstance(rows, list) or any(
                not isinstance(r, dict)
                or any(isinstance(v, (dict, list)) for v in r.values())
                for r in rows
            ):
                raise ValueError("Source must return flat objects in rows")
            all_rows.extend(rows)
            if len(all_rows) > MAX_ROWS:
                raise ValueError("Connector exceeds row limit")
            if not payload.get("has_more"):
                break
        else:
            raise ValueError(
                "Connector exceeds configured page limit; narrow the source"
            )
        if not all_rows:
            raise ValueError("Source returned no records")
        columns = list(dict.fromkeys(k for r in all_rows for k in r))
        if len(columns) > 100:
            raise ValueError("Source exceeds column limit")
        content = json.dumps(all_rows, ensure_ascii=False).encode()
        if len(content) > MAX_BYTES:
            raise ValueError("Connector exceeds size limit")
        return (
            content,
            columns,
            all_rows,
            {
                "format": "json",
                "connector": source,
                "pages": page,
                "requests": attempts,
                "endpoint": url,
                "synthetic": source == "demo",
            },
        )
    except (json.JSONDecodeError, AttributeError):
        raise ValueError("Source returned malformed JSON")
    finally:
        if own:
            client.close()

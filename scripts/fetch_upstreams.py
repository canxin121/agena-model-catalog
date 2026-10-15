#!/usr/bin/env python3
"""Fetch the registered independent upstreams into an ignored local cache.

The registry defines source scope. Models.dev is the only input to canonical
model-level fields today; OpenRouter and LiteLLM remain route observations and
Hugging Face remains an artifact inventory. Failed optional sources keep their
last successful snapshot and are explicitly marked stale in source-status.json.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "curation" / "upstreams.json"
SELECTION_PATH = ROOT / "curation" / "sources.json"
CACHE = ROOT / ".cache" / "sources"
STATUS_PATH = ROOT / ".cache" / "source-status.json"
USER_AGENT = "AgenaModelCatalog/1.0 (+https://github.com/canxin121/agena-model-catalog)"
TIMEOUT_SECONDS = 20
RETRIES = 2


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def request_bytes(url):
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    last_error = None
    for attempt in range(RETRIES):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read(), response.headers
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 < RETRIES:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after {RETRIES} attempts: {last_error}")


def decode_json(raw, source_id):
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{source_id}: response is not valid UTF-8 JSON: {error}") from error


def next_link(headers):
    for value in headers.get_all("Link", []):
        for part in value.split(","):
            match = re.match(r"\s*<([^>]+)>\s*;\s*rel=\"?next\"?", part)
            if match:
                return match.group(1)
    return None


def fetch_huggingface(source, selection):
    limit = int(source.get("max_page_size", 1000))
    organizations = {}
    total = 0
    for spec in selection.get("huggingface_organizations", []):
        organization = spec["id"]
        query = urlencode({
            "author": organization,
            "limit": limit,
            "config": "true",
            "cardData": "true",
        })
        url = f"{source['url']}?{query}"
        records = []
        page_count = 0
        while url:
            page_count += 1
            if page_count > 100:
                raise ValueError(f"huggingface/{organization}: pagination exceeded 100 pages")
            raw, headers = request_bytes(url)
            page = decode_json(raw, f"huggingface/{organization}")
            if not isinstance(page, list):
                raise ValueError(f"huggingface/{organization}: expected a list of model repositories")
            for record in page:
                if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                    raise ValueError(f"huggingface/{organization}: malformed model repository record")
                if record["id"].split("/", 1)[0] != organization:
                    raise ValueError(
                        f"huggingface/{organization}: response included out-of-scope id {record['id']!r}"
                    )
            records.extend(page)
            url = next_link(headers)
            if not url and len(page) >= limit:
                raise ValueError(
                    f"huggingface/{organization}: reached the {limit}-record page limit without a next-page link; "
                    "refusing to treat a potentially truncated listing as complete"
                )
        if not records:
            raise ValueError(f"huggingface/{organization}: no repositories returned")
        organizations[organization] = records
        total += len(records)
    return {"organizations": organizations, "record_count": total}


def validate_source(source, value):
    source_id = source["id"]
    fetcher = source["fetcher"]
    if fetcher == "models_dev":
        if not isinstance(value, dict) or len(value) < 100:
            raise ValueError("models.dev snapshot is missing most providers")
        return len(value)
    if fetcher == "openrouter_routes":
        rows = value.get("data") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) < 200:
            raise ValueError("OpenRouter response is missing most model routes")
        return len(rows)
    if fetcher == "litellm_routes":
        if not isinstance(value, dict) or len(value) < 1000:
            raise ValueError("LiteLLM response is missing most model route records")
        return len(value)
    if fetcher == "huggingface_hub":
        if not isinstance(value, dict) or not isinstance(value.get("organizations"), dict):
            raise ValueError("Hugging Face response has an invalid organization map")
        return value["record_count"]
    raise ValueError(f"{source_id}: unsupported fetcher {fetcher!r}")


def snapshot_path(source):
    if source["id"] == "models.dev":
        return ROOT / ".cache" / "models.dev.json"
    safe_id = source["id"].replace("/", "_").replace(".", "_")
    return CACHE / f"{safe_id}.json"


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def restore_published_snapshot(source):
    published_path = source.get("published_snapshot")
    if not published_path:
        return None
    published = ROOT / published_path
    if not published.is_file():
        return None
    document = read_json(published)
    source_meta = document.get("source", {})
    if source["id"] == "openrouter":
        value = {"data": [row["raw"] for row in document.get("records", [])]}
    elif source["id"] == "litellm":
        value = {
            row["route_id"]: row["raw"]
            for row in document.get("records", [])
        }
    elif source["id"] == "huggingface":
        rows_document = read_json(ROOT / "data" / "observations" / "huggingface.json")
        organizations = {}
        for row in rows_document.get("records", []):
            organizations.setdefault(row["organization"], []).append(row["raw"])
        for rows in organizations.values():
            rows.sort(key=lambda row: row.get("id", ""))
        value = {
            "organizations": organizations,
            "record_count": sum(len(rows) for rows in organizations.values()),
        }
        source_meta = rows_document.get("source", source_meta)
    else:
        return None
    return value, source_meta


def main():
    force_refresh = "--force" in sys.argv[1:]
    registry = read_json(REGISTRY_PATH)
    selection = read_json(SELECTION_PATH)
    CACHE.mkdir(parents=True, exist_ok=True)
    previous = read_json(STATUS_PATH) if STATUS_PATH.exists() else {"sources": {}}
    inventory_doc = ROOT / "data" / "source-inventory.json"
    published_inventory = read_json(inventory_doc) if inventory_doc.exists() else {"sources": []}
    inventory_by_id = {
        source["id"]: source for source in published_inventory.get("sources", [])
    }
    statuses = {}
    required_failure = None

    for source in registry["sources"]:
        source_id = source["id"]
        if source.get("mirror_of"):
            statuses[source_id] = {
                "status": "mirror",
                "mirror_of": source["mirror_of"],
                "url": source["url"],
            }
            print(f"{source_id}: mirror of {source['mirror_of']} (not fetched independently)")
            continue
        if not source.get("enabled") or source["fetcher"] in {
            "manual_client_evidence",
            "mirror",
        }:
            statuses[source_id] = {"status": "registered_only", "url": source["url"]}
            continue

        path = snapshot_path(source)
        old = previous.get("sources", {}).get(source_id, {})
        old_inventory = inventory_by_id.get(source_id, {})
        interval = int(source.get("refresh_interval_seconds", 0))
        last_success = old.get("retrieved_at") or old_inventory.get("last_successful_retrieval")
        prior_hash = old.get("sha256") or old_inventory.get("snapshot_sha256")
        cached_from_published = False
        last_success_time = parse_timestamp(last_success)
        age_seconds = (
            (datetime.now(timezone.utc) - last_success_time).total_seconds()
            if last_success_time else None
        )
        if (
            not force_refresh
            and interval
            and age_seconds is not None
            and age_seconds < interval
        ):
            if path.is_file():
                value = decode_json(path.read_bytes(), source_id)
            else:
                restored = restore_published_snapshot(source)
                if restored is None:
                    value = None
                else:
                    value, published_meta = restored
                    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                    write_atomic(path, raw)
                    cached_from_published = True
                    if not last_success:
                        last_success = published_meta.get("retrieved_at")
            if value is not None:
                try:
                    count = validate_source(source, value)
                    snapshot_bytes = path.read_bytes()
                    statuses[source_id] = {
                        "status": "current",
                        "url": source["url"],
                        "retrieved_at": last_success,
                        "sha256": prior_hash or hashlib.sha256(snapshot_bytes).hexdigest(),
                        "record_count": count,
                        "snapshot": str(path.relative_to(ROOT)),
                        "cached_from_published_snapshot": cached_from_published,
                    }
                    print(
                        f"{source_id}: reusing {count} records from the published snapshot "
                        f"(age {int(age_seconds / 3600)}h)"
                    )
                    continue
                except Exception as error:
                    print(f"{source_id}: published cache rejected; fetching fresh: {error}", file=sys.stderr)

        try:
            if source["fetcher"] == "huggingface_hub":
                value = fetch_huggingface(source, selection)
                raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            else:
                raw, _headers = request_bytes(source["url"])
                value = decode_json(raw, source_id)
            count = validate_source(source, value)
            write_atomic(path, raw)
            statuses[source_id] = {
                "status": "current",
                "url": source["url"],
                "retrieved_at": utc_now(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "record_count": count,
                "snapshot": str(path.relative_to(ROOT)),
            }
            print(f"{source_id}: fetched {count} records ({statuses[source_id]['sha256'][:12]})")
        except Exception as error:  # source failures are recorded and isolated
            if not path.is_file():
                try:
                    restored = restore_published_snapshot(source)
                except Exception:
                    restored = None
                if restored is not None:
                    value, published_meta = restored
                    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                    write_atomic(path, raw)
                    cached_from_published = True
                    prior_hash = prior_hash or published_meta.get("sha256")
            if path.is_file():
                raw = path.read_bytes()
                statuses[source_id] = {
                    "status": "stale",
                    "url": source["url"],
                    "retrieved_at": last_success,
                    "sha256": prior_hash or hashlib.sha256(raw).hexdigest(),
                    "record_count": old.get("record_count") or old_inventory.get("snapshot_record_count"),
                    "snapshot": str(path.relative_to(ROOT)),
                    "cached_from_published_snapshot": cached_from_published,
                    "error": str(error),
                }
                print(f"{source_id}: FETCH FAILED; retaining stale snapshot: {error}", file=sys.stderr)
            else:
                statuses[source_id] = {
                    "status": "unavailable",
                    "url": source["url"],
                    "error": str(error),
                }
                print(f"{source_id}: unavailable: {error}", file=sys.stderr)
            if source_id == "models.dev":
                required_failure = error

    status_document = {
        "updated_at": utc_now(),
        "sources": statuses,
    }
    write_atomic(
        STATUS_PATH,
        (json.dumps(status_document, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    if required_failure:
        raise SystemExit(f"required source models.dev fetch failed: {required_failure}")
    print(f"source status -> {STATUS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""Persistent, privacy-limited observations and published price snapshots."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .item_store import ItemStoreMixin


SOURCES = (
    {"id": "barotem", "name": "바로템", "sourceUrl": "https://www.barotem.com/product/lists/2382r902"},
    {"id": "itembay", "name": "아이템베이", "sourceUrl": "https://www.itembay.com/item/sell/game-3828/type-3"},
    {"id": "itemmania", "name": "아이템매니아", "sourceUrl": "https://www.itemmania.com/"},
)
ACTIVE_SOURCES = tuple(source for source in SOURCES if source["id"] != "itemmania")
SOURCE_HOSTS = {"barotem": "www.barotem.com", "itembay": "www.itembay.com"}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    value = utcnow() if value is None else value
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("An aware UTC timestamp is required")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _positive_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Expected a positive finite number")
    return value


def normalize_listing(value, source_id):
    """Validate the collector boundary and discard every unapproved field."""
    if not isinstance(value, dict):
        raise ValueError("Invalid listing")
    listing_id = str(value.get("id", ""))
    identifier_match = re.fullmatch(re.escape(source_id) + r":([0-9]{1,32})", listing_id)
    if not identifier_match:
        raise ValueError("Invalid public listing identifier")
    if value.get("source") != source_id or value.get("kind") not in ("ask", "completed"):
        raise ValueError("Invalid listing source or kind")
    server = value.get("server")
    if not isinstance(server, str) or not server.strip() or len(server) > 40 or any(c in server for c in "<>\r\n\t"):
        raise ValueError("Invalid server")
    price = _positive_number(value.get("priceKRW"))
    quantity = _positive_number(value.get("quantity"))
    unit_price = _positive_number(value.get("unitPrice"))
    expected = price / quantity * 1_000_000
    if not math.isfinite(expected) or not math.isclose(unit_price, expected, rel_tol=1e-7, abs_tol=0.01):
        raise ValueError("Incorrect normalized unit price")
    if not isinstance(value.get("observedAt"), str):
        raise ValueError("Missing observation timestamp")
    observed = timestamp(value["observedAt"])
    url = value.get("url", "")
    if not isinstance(url, str) or len(url) > 512:
        raise ValueError("Invalid public listing URL")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != SOURCE_HOSTS[source_id] or parts.username or parts.password:
        raise ValueError("Invalid public listing URL")
    public_id = identifier_match.group(1)
    url = ("https://www.barotem.com/product/view/" + public_id if source_id == "barotem"
           else "https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=" + public_id)
    # Generic titles prevent raw seller subjects, contact details and HTML from
    # crossing the API boundary even when a future collector accidentally adds them.
    title = "아데나 판매 매물" if value["kind"] == "ask" else "아데나 거래완료 표시"
    return {"id": listing_id, "source": source_id, "server": server.strip(), "kind": value["kind"],
            "unitPrice": unit_price, "priceKRW": price, "quantity": quantity,
            "observedAt": observed, "url": url, "title": title}


def _median(values):
    return statistics.median(values) if values else None


class Store(ItemStoreMixin):
    def __init__(self, data_dir, interval_seconds=600, pages_per_source=3, item_interval_seconds=3600):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "prices.sqlite3"
        self.interval_seconds = int(interval_seconds)
        self.pages_per_source = int(pages_per_source)
        self.item_interval_seconds = int(item_interval_seconds)
        if self.interval_seconds <= 0 or self.item_interval_seconds <= 0 or not 1 <= self.pages_per_source <= 3:
            raise ValueError("Invalid sampling configuration")
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    source TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    row_id INTEGER PRIMARY KEY, source TEXT NOT NULL, listing_id TEXT NOT NULL,
                    kind TEXT NOT NULL, server TEXT NOT NULL, unit_price REAL NOT NULL,
                    price_krw REAL NOT NULL, quantity REAL NOT NULL, observed_at TEXT NOT NULL,
                    collected_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observations_date ON observations(collected_at);
                CREATE TABLE IF NOT EXISTS history (
                    server TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, value REAL NOT NULL,
                    PRIMARY KEY(server, at)
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA journal_mode=WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def load_snapshot(self):
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
        return self._with_items(json.loads(row[0])) if row else None

    def seed_snapshot(self, previous):
        """Import a published sample without pretending it was collected again.

        Scheduled runners can restore their last published JSON instead of
        committing a database or private upstream response into Git. Invalid
        rows and history points are discarded at this public-data boundary.
        """
        if not isinstance(previous, dict) or type(previous.get("schemaVersion")) is not int or previous.get("schemaVersion") != 1:
            raise ValueError("Unsupported previous snapshot")
        if not isinstance(previous.get("generatedAt"), str) or not isinstance(previous.get("nextUpdateAt"), str):
            raise ValueError("Missing previous snapshot timestamps")
        generated_at = timestamp(previous.get("generatedAt"))
        next_update_at = timestamp(previous.get("nextUpdateAt"))
        raw_sources = previous.get("sources")
        raw_listings = previous.get("listings")
        if not isinstance(raw_sources, list) or not isinstance(raw_listings, list):
            raise ValueError("Invalid previous snapshot")
        metadata = {source.get("id"): source for source in raw_sources if isinstance(source, dict)
                    and isinstance(source.get("id"), str) and source.get("id") in SOURCE_HOSTS}
        valid_by_source = {source["id"]: [] for source in ACTIVE_SOURCES}
        seen = set()
        for row in raw_listings:
            try:
                source_id = row.get("source")
                if source_id not in SOURCE_HOSTS or source_id not in metadata:
                    continue
                updated_at = metadata[source_id].get("updatedAt")
                if not isinstance(updated_at, str):
                    continue
                if timestamp(updated_at) > generated_at:
                    continue
                normalized = normalize_listing(row, source_id)
                key = (source_id, normalized["id"], normalized["kind"])
                if key not in seen:
                    seen.add(key)
                    valid_by_source[source_id].append(normalized)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                continue
        listings = [row for rows in valid_by_source.values() for row in rows]
        if not listings:
            raise ValueError("Previous snapshot has no usable prices")
        if "items" in previous:
            self.seed_item_snapshot(previous["items"], currency_generated_at=generated_at)
        states = []
        for source in SOURCES:
            source_id = source["id"]
            rows = valid_by_source.get(source_id, [])
            prior = metadata.get(source_id, {})
            status = prior.get("status") if rows else "pending"
            status = status if status in ("ok", "error") else "pending"
            updated_at = timestamp(prior["updatedAt"]) if rows else None
            pages = prior.get("pagesFetched", 0)
            pages = pages if isinstance(pages, int) and not isinstance(pages, bool) and 0 <= pages <= self.pages_per_source + 1 else 0
            total = prior.get("totalListings")
            total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
            rejected = prior.get("rejectedCount", 0)
            rejected = rejected if isinstance(rejected, int) and not isinstance(rejected, bool) and rejected >= 0 else 0
            states.append({**source, "status": status, "updatedAt": updated_at,
                           "error": "이전 수집에서 오류가 발생했습니다." if status == "error" else None,
                           "sampleCount": len(rows), "completedCount": sum(row["kind"] == "completed" for row in rows),
                           "pagesFetched": pages, "totalListings": total, "rejectedCount": rejected,
                           "warnings": ["이전 수집에 일부 누락이 있었습니다."] if rows and prior.get("warnings") else [],
                           "stale": status != "ok"})
        servers = self._aggregate(listings, states)
        known_servers = {server["name"]: server for server in servers}
        history = []
        raw_servers = previous.get("servers", [])
        for raw_server in raw_servers if isinstance(raw_servers, list) else []:
            if not isinstance(raw_server, dict) or raw_server.get("name") not in known_servers:
                continue
            points = raw_server.get("history", [])
            for point in points[-144:] if isinstance(points, list) else []:
                try:
                    if not isinstance(point, dict) or not isinstance(point.get("at"), str):
                        continue
                    at = timestamp(point["at"])
                    if at > generated_at or at < timestamp(parse_timestamp(generated_at) - timedelta(days=7)):
                        continue
                    kind = point.get("kind", raw_server.get("historyKind"))
                    if kind not in ("ask", "completed"):
                        continue
                    value = _positive_number(point.get("value"))
                    history.append((raw_server["name"], at, kind, value))
                except (ValueError, TypeError, OverflowError):
                    continue
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
            if existing_row:
                existing = json.loads(existing_row[0])
                if existing.get("listings") and existing.get("generatedAt", "") >= generated_at:
                    return self._with_items(existing)
            for state in states:
                rows = valid_by_source.get(state["id"], [])
                if not rows:
                    continue
                connection.execute("INSERT INTO source_snapshots VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                                   (state["id"], state["updatedAt"], encode_json({"listings": rows}).decode()))
                for row in rows:
                    connection.execute("""INSERT INTO observations(source,listing_id,kind,server,unit_price,price_krw,quantity,observed_at,collected_at)
                        SELECT ?,?,?,?,?,?,?,?,? WHERE NOT EXISTS
                        (SELECT 1 FROM observations WHERE source=? AND listing_id=? AND kind=? AND collected_at=?)""",
                        (state["id"], row["id"], row["kind"], row["server"], row["unitPrice"], row["priceKRW"], row["quantity"], row["observedAt"], state["updatedAt"],
                         state["id"], row["id"], row["kind"], state["updatedAt"]))
            connection.executemany("INSERT OR IGNORE INTO history VALUES(?,?,?,?)", history)
            for server in servers:
                points = list(connection.execute("SELECT at,value,kind FROM history WHERE server=? ORDER BY at DESC LIMIT 144", (server["name"],)))
                server["history"] = [{"at": row[0], "value": row[1], "kind": row[2]} for row in reversed(points)]
            payload = self._payload(listings, states, servers, generated_at, next_update_at)
            connection.execute("INSERT INTO metadata VALUES('snapshot',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode_json(payload).decode(),))
        return self._with_items(payload)

    def empty_snapshot(self, now=None, next_update_at=None):
        now = timestamp(now)
        next_update_at = timestamp(next_update_at) if next_update_at else timestamp(parse_timestamp(now) + timedelta(seconds=self.interval_seconds))
        return self._payload([], [{**source, "status": "pending", "updatedAt": None,
                                  "error": None, "sampleCount": 0, "completedCount": 0,
                                  "pagesFetched": 0, "totalListings": None, "rejectedCount": 0,
                                  "warnings": [], "stale": True} for source in SOURCES], [], now, next_update_at)

    def apply_cycle(self, results, *, now=None, next_update_at=None):
        """Atomically replace successful sources and retain failed source data."""
        now = timestamp(now)
        next_update_at = timestamp(next_update_at) if next_update_at else timestamp(parse_timestamp(now) + timedelta(seconds=self.interval_seconds))
        if not isinstance(results, dict):
            raise ValueError("Invalid collection result")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_row = connection.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
            previous = json.loads(previous_row[0]) if previous_row else {}
            previous_sources = {source["id"]: source for source in previous.get("sources", [])}
            snapshots = {row[0]: (row[1], json.loads(row[2])) for row in connection.execute("SELECT source,updated_at,payload FROM source_snapshots")}
            source_states, all_listings, succeeded = [], [], []
            for source in SOURCES:
                source_id = source["id"]
                prior = snapshots.get(source_id)
                prior_state = previous_sources.get(source_id, {})
                result = results.get(source_id)
                valid, rejected, error = [], 0, None
                if source_id == "itemmania":
                    state = {**source, "status": "pending", "updatedAt": None, "error": None,
                             "sampleCount": 0, "completedCount": 0, "pagesFetched": 0,
                             "totalListings": None, "rejectedCount": 0, "warnings": [], "stale": True}
                    source_states.append(state)
                    continue
                if isinstance(result, BaseException):
                    error = "공개 목록 수집에 실패했습니다 (" + type(result).__name__[:60] + ")."
                elif not isinstance(result, dict) or not isinstance(result.get("listings"), list):
                    error = "유효한 수집 결과를 확인하지 못했습니다."
                else:
                    seen = set()
                    for listing in result["listings"]:
                        try:
                            normalized = normalize_listing(listing, source_id)
                            key = (normalized["id"], normalized["kind"])
                            if key in seen:
                                continue
                            seen.add(key)
                            valid.append(normalized)
                        except (ValueError, TypeError, KeyError, OverflowError):
                            rejected += 1
                    reported_rejected = result.get("rejectedCount", 0)
                    all_rejected = isinstance(reported_rejected, int) and not isinstance(reported_rejected, bool) and reported_rejected > 0
                    if not valid and (result["listings"] or all_rejected):
                        error = "유효한 가격과 수량을 확인하지 못했습니다."
                if error:
                    source_data = prior[1] if prior else {"listings": []}
                    updated_at = prior[0] if prior else None
                    state = {**source, **{key: prior_state.get(key, default) for key, default in (
                        ("pagesFetched", 0), ("totalListings", None), ("rejectedCount", 0), ("warnings", []))},
                        "status": "error", "updatedAt": updated_at, "error": error, "stale": True}
                else:
                    source_data = {"listings": valid}
                    updated_at = now
                    succeeded.append(source_id)
                    connection.execute("INSERT INTO source_snapshots VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                                       (source_id, now, encode_json(source_data).decode()))
                    connection.executemany("INSERT INTO observations(source,listing_id,kind,server,unit_price,price_krw,quantity,observed_at,collected_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                           [(source_id, row["id"], row["kind"], row["server"], row["unitPrice"], row["priceKRW"], row["quantity"], row["observedAt"], now) for row in valid])
                    total = result.get("totalListings")
                    total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
                    pages = result.get("pagesFetched", 0)
                    pages = pages if isinstance(pages, int) and not isinstance(pages, bool) and 0 <= pages <= self.pages_per_source + 1 else 0
                    supplied_rejected = result.get("rejectedCount", 0)
                    supplied_rejected = supplied_rejected if isinstance(supplied_rejected, int) and not isinstance(supplied_rejected, bool) and supplied_rejected >= 0 else 0
                    warnings = result.get("warnings", [])
                    warnings = [text[:240] for text in warnings[:8] if isinstance(text, str)] if isinstance(warnings, list) else []
                    state = {**source, "status": "ok", "updatedAt": now, "error": None,
                             "pagesFetched": pages, "totalListings": total,
                             "rejectedCount": supplied_rejected + rejected, "warnings": warnings, "stale": False}
                rows = source_data["listings"]
                state["sampleCount"] = len(rows)
                state["completedCount"] = sum(row["kind"] == "completed" for row in rows)
                all_listings.extend(rows)
                source_states.append(state)
            servers = self._aggregate(all_listings, source_states)
            # A failed source does not manufacture a new history observation.
            for server in servers:
                fresh_rows = [row for row in all_listings if row["server"] == server["name"] and row["source"] in succeeded]
                fresh_asks = [row["unitPrice"] for row in fresh_rows if row["kind"] == "ask"]
                fresh_completed = [row["unitPrice"] for row in fresh_rows if row["kind"] == "completed"]
                if fresh_asks or fresh_completed:
                    kind = "ask" if fresh_asks else "completed"
                    value = _median(fresh_asks or fresh_completed)
                    connection.execute("INSERT OR REPLACE INTO history VALUES(?,?,?,?)", (server["name"], now, kind, value))
            cutoff = timestamp(parse_timestamp(now) - timedelta(days=30))
            connection.execute("DELETE FROM observations WHERE collected_at < ?", (cutoff,))
            connection.execute("DELETE FROM history WHERE at < ?", (cutoff,))
            history_cutoff = timestamp(parse_timestamp(now) - timedelta(days=7))
            for server in servers:
                history = list(connection.execute("SELECT at,value,kind FROM history WHERE server=? AND at>=? ORDER BY at DESC LIMIT 144", (server["name"], history_cutoff)))
                server["history"] = [{"at": row[0], "value": row[1], "kind": row[2]} for row in reversed(history)]
                server["historyKind"] = "ask" if server["askMedian"] is not None else "completed"
            payload = self._payload(all_listings, source_states, servers, now, next_update_at)
            connection.execute("INSERT INTO metadata VALUES('snapshot',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode_json(payload).decode(),))
        return self._with_items(payload)

    def _aggregate(self, listings, sources):
        states = {source["id"]: source for source in sources}
        result = []
        for name in sorted({listing["server"] for listing in listings}):
            rows = [row for row in listings if row["server"] == name]
            asks = [row["unitPrice"] for row in rows if row["kind"] == "ask"]
            completed = [row["unitPrice"] for row in rows if row["kind"] == "completed"]
            source_stats = []
            for source in ACTIVE_SOURCES:
                source_rows = [row for row in rows if row["source"] == source["id"]]
                if not source_rows:
                    continue
                source_asks = [row["unitPrice"] for row in source_rows if row["kind"] == "ask"]
                source_completed = [row["unitPrice"] for row in source_rows if row["kind"] == "completed"]
                state = states[source["id"]]
                source_stats.append({"id": source["id"], "name": source["name"], "askMedian": _median(source_asks),
                                     "completedMedian": _median(source_completed), "count": len(source_rows),
                                     "listingCount": len(source_asks), "completedCount": len(source_completed),
                                     "updatedAt": state["updatedAt"], "status": state["status"]})
            result.append({"name": name, "count": len(rows), "listingCount": len(asks), "completedCount": len(completed),
                           "askMedian": _median(asks), "completedMedian": _median(completed),
                           "minAsk": min(asks) if asks else None, "maxAsk": max(asks) if asks else None,
                           "sourceStats": source_stats, "history": [],
                           "historyKind": "ask" if asks else "completed"})
        return result

    def _payload(self, listings, sources, servers, now, next_update_at):
        successful_times = [source["updatedAt"] for source in sources if source["updatedAt"]]
        return {"schemaVersion": 1, "game": "리니지 클래식", "units": "KRW_PER_1M_ADENA",
                "intervalSeconds": self.interval_seconds, "generatedAt": now, "nextUpdateAt": next_update_at,
                "lastSuccessfulUpdateAt": max(successful_times) if successful_times else None,
                "stale": not successful_times or any(source["status"] == "error" for source in sources),
                "sources": sources, "servers": servers, "listings": listings,
                "coverage": {"mode": "sample", "pagesPerSource": self.pages_per_source,
                             "maxRows": self.pages_per_source * (60 + 48) + 48,
                             "message": "일반 매물 일부 페이지와 아이템베이 완료표시 표본입니다. 전체 서버·전체 매물을 대표하지 않습니다."}}

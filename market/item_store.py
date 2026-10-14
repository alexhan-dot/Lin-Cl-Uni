"""Independent item observations, with explicit identity and price boundaries.

The catalog is maintained separately from seller subjects. Only catalog names
cross this boundary; unknown enchantment and blessing remain unknown rather
than being combined with an explicitly described variant.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import timedelta


ITEM_SOURCES = (
    {"id": "barotem", "name": "바로템", "sourceUrl": "https://www.barotem.com/product/lists/2381r870"},
    {"id": "itembay", "name": "아이템베이", "sourceUrl": "https://www.itembay.com/item/sell/game-3828/type-4"},
    {"id": "itemmania", "name": "아이템매니아", "sourceUrl": "https://www.itemmania.com/"},
)
BLESSINGS = {"normal", "blessed", "cursed", "unknown"}
_WARNING = "정식명 또는 등록된 별칭이 명확한 단일 품목만 비교합니다. 미확인·묶음 매물은 제외합니다."


def _count(value, default=0, maximum=None):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        return default
    return value


def normalize_item_listing(value, source_id):
    from .item_catalog import MAPPING_VERSION, get_item
    from .store import _positive_number, normalize_listing

    if not isinstance(value, dict):
        raise ValueError("Invalid item listing")
    entry = get_item(value.get("itemId"))
    if not entry or value.get("itemName") != entry["name"]:
        raise ValueError("Unregistered item identity")
    enchant = value.get("enchant")
    if enchant is not None and (type(enchant) is not int or not 0 <= enchant <= 15):
        raise ValueError("Invalid item enchantment")
    if entry.get("enhanceable") is False and enchant not in (None, 0):
        raise ValueError("This item cannot be enchanted")
    blessing = value.get("blessing")
    if blessing not in BLESSINGS:
        raise ValueError("Invalid item blessing")
    if entry.get("inherentBlessing") in BLESSINGS - {"unknown"} and blessing != entry["inherentBlessing"]:
        raise ValueError("Blessing conflicts with the canonical item")
    price = _positive_number(value.get("priceKRW"))
    quantity = _positive_number(value.get("quantity"))
    if not float(quantity).is_integer():
        raise ValueError("Item count must be an integer")
    unit_price = _positive_number(value.get("unitPrice"))
    expected = price / quantity
    if not math.isfinite(expected) or not math.isclose(unit_price, expected, rel_tol=1e-7, abs_tol=.01):
        raise ValueError("Incorrect item unit price")
    # Reuse the currency boundary's identifier, server, timestamp and URL checks.
    normalized = normalize_listing({**value, "unitPrice": expected * 1_000_000}, source_id)
    normalized.update(itemId=entry["id"], itemName=entry["name"], enchant=enchant,
                      blessing=blessing, mappingVersion=MAPPING_VERSION,
                      unitPrice=round(expected, 6), quantity=int(quantity), title=entry["name"])
    return normalized


def _retained_item_listing(value, source_id):
    """Keep a stable identity when a catalog corrects its display spelling."""
    from .item_catalog import get_item
    if not isinstance(value, dict):
        raise ValueError("Invalid retained item")
    entry = get_item(value.get("itemId"))
    if not entry:
        raise ValueError("Removed item identity")
    return normalize_item_listing({**value, "itemName": entry["name"]}, source_id)


def aggregate_items(listings, sources):
    from .store import _median

    states = {source["id"]: source for source in sources}
    grouped = defaultdict(list)
    for row in listings:
        grouped[(row["itemId"], row["server"], row["enchant"], row["blessing"])].append(row)
    groups = []
    for (item_id, server, enchant, blessing), rows in grouped.items():
        asks = [row["unitPrice"] for row in rows if row["kind"] == "ask"]
        completed = [row["unitPrice"] for row in rows if row["kind"] == "completed"]
        source_stats = []
        for source in ITEM_SOURCES[:2]:
            samples = [row for row in rows if row["source"] == source["id"]]
            if not samples:
                continue
            source_asks = [row["unitPrice"] for row in samples if row["kind"] == "ask"]
            source_completed = [row["unitPrice"] for row in samples if row["kind"] == "completed"]
            state = states[source["id"]]
            source_stats.append({"id": source["id"], "name": source["name"],
                                 "askMedian": _median(source_asks), "completedMedian": _median(source_completed),
                                 "listingCount": len(source_asks), "completedCount": len(source_completed),
                                 "count": len(samples), "updatedAt": state["updatedAt"], "status": state["status"]})
        groups.append({"itemId": item_id, "itemName": rows[0]["itemName"], "server": server,
                       "enchant": enchant, "blessing": blessing, "count": len(rows),
                       "askMedian": _median(asks), "completedMedian": _median(completed),
                       "minAsk": min(asks) if asks else None, "maxAsk": max(asks) if asks else None,
                       "listingCount": len(asks), "completedCount": len(completed), "sourceStats": source_stats})
    return sorted(groups, key=lambda group: (group["itemName"], group["server"],
                                            -1 if group["enchant"] is None else group["enchant"], group["blessing"]))


class ItemStoreMixin:
    def load_item_snapshot(self):
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='item_snapshot'").fetchone()
        return json.loads(row[0]) if row else None

    def _with_items(self, payload):
        items = self.load_item_snapshot()
        return {**payload, "items": items} if items is not None else payload

    def items_due(self, now=None):
        from .item_catalog import MAPPING_VERSION
        from .store import parse_timestamp, timestamp
        previous = self.load_item_snapshot()
        if not previous:
            return True
        if previous.get("mappingVersion") != MAPPING_VERSION:
            return True
        return parse_timestamp(timestamp(now)) >= parse_timestamp(previous["nextUpdateAt"])

    def _item_payload(self, rows, states, now, next_update_at):
        from .item_catalog import MAPPING_VERSION, public_catalog

        successful = [state["updatedAt"] for state in states if state["updatedAt"]]
        return {"units": "KRW_PER_ITEM", "mappingVersion": MAPPING_VERSION, "intervalSeconds": self.item_interval_seconds,
                "generatedAt": now, "nextUpdateAt": next_update_at,
                "lastSuccessfulUpdateAt": max(successful) if successful else None,
                "stale": not successful or any(state["status"] == "error" for state in states),
                "sources": states, "listings": rows, "groups": aggregate_items(rows, states),
                "catalog": public_catalog(),
                "coverage": {"mode": "sample", "pagesPerSource": self.pages_per_source,
                             "matchedCount": len(rows),
                             "excludedCount": sum(state["rejectedCount"] + state.get("unmappedCount", 0)
                                                  + state.get("ambiguousCount", 0) for state in states),
                             "message": _WARNING}}

    def empty_item_snapshot(self, now=None, next_update_at=None):
        from .store import parse_timestamp, timestamp
        now = timestamp(now)
        next_update_at = timestamp(next_update_at) if next_update_at else timestamp(parse_timestamp(now) + timedelta(seconds=self.item_interval_seconds))
        states = [{**source, "status": "pending", "updatedAt": None, "error": None,
                   "sampleCount": 0, "completedCount": 0, "pagesFetched": 0, "totalListings": None,
                   "rejectedCount": 0, "unmappedCount": 0, "ambiguousCount": 0, "invalidCount": 0, "rawCount": 0,
                   "excludedCounts": {"unmapped": 0, "ambiguous": 0, "invalid": 0},
                   "warnings": [], "stale": True} for source in ITEM_SOURCES]
        return self._item_payload([], states, now, next_update_at)

    def apply_item_cycle(self, results, *, now=None, next_update_at=None):
        from .store import encode_json, parse_timestamp, timestamp
        if not isinstance(results, dict):
            raise ValueError("Invalid item collection result")
        now = timestamp(now)
        next_update_at = timestamp(next_update_at) if next_update_at else timestamp(parse_timestamp(now) + timedelta(seconds=self.item_interval_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute("SELECT value FROM metadata WHERE key='item_snapshot'").fetchone()
            previous = json.loads(record[0]) if record else {}
            prior_states = {state["id"]: state for state in previous.get("sources", [])}
            states, all_rows = [], []
            for source in ITEM_SOURCES:
                source_id = source["id"]
                if source_id == "itemmania":
                    states.append({**source, "status": "pending", "updatedAt": None, "error": None,
                                   "sampleCount": 0, "completedCount": 0, "pagesFetched": 0,
                                   "totalListings": None, "rejectedCount": 0,
                                   "unmappedCount": 0, "ambiguousCount": 0, "invalidCount": 0, "rawCount": 0,
                                   "excludedCounts": {"unmapped": 0, "ambiguous": 0, "invalid": 0},
                                   "warnings": [], "stale": True})
                    continue
                result = results.get(source_id)
                error, rows, rejected = None, [], 0
                if isinstance(result, BaseException):
                    error = "공개 아이템 목록 수집에 실패했습니다."
                elif not isinstance(result, dict) or not isinstance(result.get("listings"), list):
                    error = "유효한 아이템 수집 결과를 확인하지 못했습니다."
                else:
                    seen = set()
                    for row in result["listings"]:
                        try:
                            valid = normalize_item_listing(row, source_id)
                            key = (valid["id"], valid["kind"])
                            if key not in seen:
                                rows.append(valid)
                                seen.add(key)
                        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                            rejected += 1
                    if not rows and result["listings"]:
                        error = "유효한 아이템 이름과 가격을 확인하지 못했습니다."
                    excluded = result.get("excludedCounts")
                    excluded = excluded if isinstance(excluded, dict) else {}
                    invalid = _count(excluded.get("invalid", result.get("invalidCount")))
                    raw_count = _count(result.get("rawCount"))
                    if not rows and raw_count > 0 and invalid >= raw_count:
                        error = "공개 목록에서 유효한 아이템 매물을 확인하지 못했습니다."
                prior = prior_states.get(source_id, {})
                if error:
                    rows = []
                    for row in previous.get("listings", []):
                        try:
                            if row.get("source") == source_id:
                                rows.append(_retained_item_listing(row, source_id))
                        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                            continue
                    state = {**source, "status": "error", "updatedAt": prior.get("updatedAt"), "error": error,
                             "pagesFetched": prior.get("pagesFetched", 0), "totalListings": prior.get("totalListings"),
                             "rejectedCount": prior.get("rejectedCount", 0),
                             **{key: _count(prior.get(key)) for key in ("unmappedCount", "ambiguousCount", "invalidCount", "rawCount")},
                             "excludedCounts": {key: _count(prior.get(key + "Count")) for key in ("unmapped", "ambiguous", "invalid")},
                             "warnings": [_WARNING], "stale": True}
                else:
                    state = {**source, "status": "ok", "updatedAt": now, "error": None,
                             "pagesFetched": _count(result.get("pagesFetched"), maximum=self.pages_per_source + 1),
                             "totalListings": _count(result.get("totalListings"), default=None),
                             "rejectedCount": rejected + _count(result.get("rejectedCount")),
                             "warnings": [_WARNING], "stale": False}
                    for key in ("unmappedCount", "ambiguousCount", "invalidCount"):
                        state[key] = _count(excluded.get(key.removesuffix("Count"), result.get(key)))
                    state["rawCount"] = raw_count
                    state["excludedCounts"] = {"unmapped": state["unmappedCount"],
                                               "ambiguous": state["ambiguousCount"], "invalid": state["invalidCount"]}
                state.update(sampleCount=len(rows), completedCount=sum(row["kind"] == "completed" for row in rows))
                states.append(state)
                all_rows.extend(rows)
            payload = self._item_payload(all_rows, states, now, next_update_at)
            connection.execute("INSERT INTO metadata VALUES('item_snapshot',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode_json(payload).decode(),))
        return payload

    def seed_item_snapshot(self, raw, *, currency_generated_at):
        """Rebuild identity/groups from safe listings, preserving source ages."""
        from .store import encode_json, parse_timestamp, timestamp
        if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list) or not isinstance(raw.get("listings"), list):
            return None
        try:
            generated = timestamp(raw["generatedAt"])
            if generated > currency_generated_at:
                return None
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        raw_states = {source.get("id"): source for source in raw["sources"]
                      if isinstance(source, dict) and isinstance(source.get("id"), str)}
        states, rows, seen = [], [], set()
        for source in ITEM_SOURCES:
            source_id = source["id"]
            prior = raw_states.get(source_id, {})
            updated_at = None
            if source_id != "itemmania":
                try:
                    updated_at = timestamp(prior["updatedAt"])
                    if updated_at > generated:
                        updated_at = None
                except (ValueError, TypeError, KeyError, OverflowError):
                    pass
            source_rows = []
            if updated_at:
                for row in raw["listings"]:
                    try:
                        if not isinstance(row, dict) or row.get("source") != source_id:
                            continue
                        valid = _retained_item_listing(row, source_id)
                        if valid["observedAt"] > generated:
                            continue
                        key = (valid["id"], valid["kind"])
                        if key not in seen:
                            seen.add(key)
                            source_rows.append(valid)
                    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                        continue
            status = prior.get("status") if updated_at else "pending"
            status = status if status in ("ok", "error") else "pending"
            states.append({**source, "status": status, "updatedAt": updated_at,
                           "error": "이전 아이템 수집에 오류가 발생했습니다." if status == "error" else None,
                           "sampleCount": len(source_rows), "completedCount": sum(row["kind"] == "completed" for row in source_rows),
                           "pagesFetched": _count(prior.get("pagesFetched"), maximum=self.pages_per_source + 1),
                           "totalListings": _count(prior.get("totalListings"), default=None),
                           "rejectedCount": _count(prior.get("rejectedCount")),
                           **{key: _count(prior.get(key)) for key in ("unmappedCount", "ambiguousCount", "invalidCount", "rawCount")},
                           "excludedCounts": {key: _count(prior.get(key + "Count")) for key in ("unmapped", "ambiguous", "invalid")},
                           "warnings": [_WARNING] if source_id != "itemmania" else [], "stale": status != "ok"})
            rows.extend(source_rows)
        next_update = timestamp(parse_timestamp(generated) + timedelta(seconds=self.item_interval_seconds))
        try:
            prior_next = timestamp(raw["nextUpdateAt"])
            if generated <= prior_next <= next_update:
                next_update = prior_next
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
        payload = self._item_payload(rows, states, generated, next_update)
        # Rebuild the public catalog from current vetted definitions, but keep
        # the version of the actual observation so changed mappings are sampled
        # immediately on the next runner instead of waiting for the old hour.
        observed_version = raw.get("mappingVersion")
        if not isinstance(observed_version, str):
            raw_catalog = raw.get("catalog")
            observed_version = raw_catalog.get("mappingVersion") if isinstance(raw_catalog, dict) else None
        if observed_version != payload["mappingVersion"]:
            payload["mappingVersion"] = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute("SELECT value FROM metadata WHERE key='item_snapshot'").fetchone()
            if record and json.loads(record[0])["generatedAt"] >= generated:
                return json.loads(record[0])
            connection.execute("INSERT INTO metadata VALUES('item_snapshot',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode_json(payload).decode(),))
        return payload

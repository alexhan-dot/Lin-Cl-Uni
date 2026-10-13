"""Offline regression checks for persistence, privacy, scheduling, and HTTP.

Run with ``python -m unittest discover -s market/tests -v``. Fixtures are public
listing-shaped synthetic data; these tests never contact a marketplace.
"""

from __future__ import annotations

import copy
import json
import math
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from market.server import PriceService, create_server
from market.store import Store


START = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
START_TEXT = "2026-01-02T03:04:05Z"


def listing(source="barotem", identifier="101", *, kind="ask", price=6200,
            quantity=1_000_000, server="데포로쥬"):
    """A safe, normalized listing including its canonical public destination."""
    url = ("https://www.barotem.com/product/view/" + identifier if source == "barotem"
           else "https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=" + identifier)
    return {"id": source + ":" + identifier, "source": source, "server": server,
            "kind": kind, "unitPrice": price / quantity * 1_000_000,
            "priceKRW": price, "quantity": quantity, "observedAt": START_TEXT,
            "url": url, "title": "리니지 클래식 아데나"}


def result(*rows, total=10, warnings=()):
    return {"listings": list(rows), "totalListings": total, "pagesFetched": 1,
            "rejectedCount": 0, "warnings": list(warnings)}


def fixture_results():
    return {"barotem": result(listing()),
            "itembay": result(listing("itembay", "201", price=6500),
                              listing("itembay", "202", kind="completed", price=6300))}


class TemporaryStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)
        self.store = Store(self.data_dir, interval_seconds=600, pages_per_source=3)

    def cycle(self, values=None, now=START):
        return self.store.apply_cycle(fixture_results() if values is None else values,
                                     now=now, next_update_at=now + timedelta(seconds=600))


def source_record(payload, source_id):
    sources = payload["sources"]
    if isinstance(sources, dict):
        return sources[source_id]
    return next(source for source in sources if source["id"] == source_id)


class StoreTests(TemporaryStoreTest):
    def test_ask_and_completed_prices_have_separate_statistics(self):
        payload = self.cycle()
        server = next(row for row in payload["servers"] if row["name"] == "데포로쥬")
        self.assertEqual(server["askMedian"], 6350)
        self.assertEqual(server["completedMedian"], 6300)
        self.assertEqual(server["minAsk"], 6200)
        self.assertEqual(server["maxAsk"], 6500)
        item_stats = next(row for row in server["sourceStats"] if row["id"] == "itembay")
        self.assertEqual(item_stats["askMedian"], 6500)
        self.assertEqual(item_stats["completedMedian"], 6300)

    def test_same_public_identifier_keeps_ask_and_completed_observations_distinct(self):
        ask = listing("itembay", "201", price=6500)
        completed = listing("itembay", "201", kind="completed", price=6300)
        payload = self.cycle({"barotem": result(),
                              "itembay": result(ask, ask, completed, completed)})
        self.assertEqual(len(payload["listings"]), 2)
        self.assertEqual({row["kind"] for row in payload["listings"]}, {"ask", "completed"})

    def test_restart_loads_identical_cached_snapshot(self):
        self.assertIsNone(self.store.load_snapshot())
        expected = self.cycle()
        restarted = Store(self.data_dir, interval_seconds=600, pages_per_source=3)
        self.assertEqual(restarted.load_snapshot(), expected)
        self.assertEqual(len(expected["listings"]), 3)

    def test_one_failure_retains_only_that_sources_previous_data_and_timestamp(self):
        first = self.cycle()
        failed_before = copy.deepcopy(source_record(first, "barotem"))
        failed_rows_before = [row for row in first["listings"] if row["source"] == "barotem"]
        next_time = START + timedelta(seconds=600)
        current = self.cycle({"barotem": RuntimeError("seller-secret: do not publish"),
                              "itembay": result(listing("itembay", "203", price=6900))},
                             now=next_time)
        failed_after = source_record(current, "barotem")
        self.assertEqual(failed_after["updatedAt"], failed_before["updatedAt"])
        self.assertEqual([row for row in current["listings"] if row["source"] == "barotem"],
                         failed_rows_before)
        successful_after = source_record(current, "itembay")
        self.assertNotEqual(successful_after["updatedAt"],
                            source_record(first, "itembay")["updatedAt"])
        self.assertEqual([row["id"] for row in current["listings"] if row["source"] == "itembay"],
                         ["itembay:203"])
        self.assertNotIn("seller-secret", json.dumps(current, ensure_ascii=False))

    def test_failed_first_cycle_has_no_invented_successful_observation(self):
        payload = self.cycle({"barotem": RuntimeError("offline"),
                              "itembay": RuntimeError("offline")})
        self.assertEqual(payload["listings"], [])
        self.assertIsNone(source_record(payload, "barotem")["updatedAt"])
        self.assertIsNone(source_record(payload, "itembay")["updatedAt"])

    def test_empty_all_rejected_result_retains_last_good_source_data_and_timestamp(self):
        first = self.cycle()
        rejected = result(total=400)
        rejected["rejectedCount"] = 192
        current = self.cycle({"barotem": rejected,
                              "itembay": result(listing("itembay", "203", price=6900))},
                             now=START + timedelta(seconds=600))
        state = source_record(current, "barotem")
        self.assertEqual(state["status"], "error")
        self.assertTrue(state["stale"])
        self.assertEqual(state["updatedAt"], source_record(first, "barotem")["updatedAt"])
        self.assertEqual([row for row in current["listings"] if row["source"] == "barotem"],
                         [row for row in first["listings"] if row["source"] == "barotem"])
        self.assertEqual(source_record(current, "itembay")["status"], "ok")
        self.assertEqual([row["id"] for row in current["listings"] if row["source"] == "itembay"],
                         ["itembay:203"])

    def test_first_empty_all_rejected_cycle_has_no_invented_success(self):
        rejected = result(total=400)
        rejected["rejectedCount"] = 192
        payload = self.cycle({"barotem": copy.deepcopy(rejected),
                              "itembay": copy.deepcopy(rejected)})
        self.assertEqual(payload["listings"], [])
        self.assertEqual(payload["servers"], [])
        self.assertIsNone(payload["lastSuccessfulUpdateAt"])
        self.assertTrue(payload["stale"])
        for source_id in ("barotem", "itembay"):
            with self.subTest(source=source_id):
                state = source_record(payload, source_id)
                self.assertEqual(state["status"], "error")
                self.assertIsNone(state["updatedAt"])
                self.assertEqual(state["sampleCount"], 0)

    def test_genuine_empty_success_replaces_old_listings_and_updates_source_timestamp(self):
        first = self.cycle()
        payload = self.cycle({"barotem": result(total=0), "itembay": result(total=0)},
                             now=START + timedelta(seconds=600))
        self.assertEqual(payload["listings"], [])
        self.assertEqual(payload["servers"], [])
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["lastSuccessfulUpdateAt"], "2026-01-02T03:14:05Z")
        for source_id in ("barotem", "itembay"):
            with self.subTest(source=source_id):
                state = source_record(payload, source_id)
                self.assertEqual(state["status"], "ok")
                self.assertEqual(state["updatedAt"], payload["lastSuccessfulUpdateAt"])
                self.assertNotEqual(state["updatedAt"], source_record(first, source_id)["updatedAt"])
                self.assertEqual(state["sampleCount"], 0)
                self.assertEqual(state["rejectedCount"], 0)

    def test_failed_source_does_not_manufacture_new_history_points(self):
        first = self.cycle({"barotem": result(listing(server="데포로쥬")),
                            "itembay": result(listing("itembay", "201", server="켄라우헬"))})
        old_history = next(row["history"] for row in first["servers"]
                           if row["name"] == "데포로쥬")
        self.assertEqual(len(old_history), 1)
        current = self.cycle({"barotem": RuntimeError("offline"),
                              "itembay": result(listing("itembay", "202", server="켄라우헬",
                                                        price=6900))},
                             now=START + timedelta(seconds=600))
        retained = next(row for row in current["servers"] if row["name"] == "데포로쥬")
        fresh = next(row for row in current["servers"] if row["name"] == "켄라우헬")
        self.assertEqual(retained["history"], old_history)
        self.assertEqual(len(fresh["history"]), 2)
        self.assertEqual(fresh["history"][-1]["value"], 6900)

    def test_store_rejects_nonfinite_negative_and_zero_listing_numbers(self):
        invalid = []
        for field in ("priceKRW", "quantity", "unitPrice"):
            for value in (float("nan"), float("inf"), float("-inf"), -1, 0, True):
                row = listing(identifier=str(300 + len(invalid)))
                row[field] = value
                invalid.append(row)
        valid = listing(identifier="900")
        payload = self.cycle({"barotem": result(valid, *invalid),
                              "itembay": result()})
        self.assertEqual([row["id"] for row in payload["listings"]], ["barotem:900"])
        for row in payload["listings"]:
            for field in ("priceKRW", "quantity", "unitPrice"):
                self.assertTrue(math.isfinite(row[field]))
                self.assertGreater(row[field], 0)
        json.dumps(payload, allow_nan=False)

    def test_listing_whitelist_drops_identity_and_uses_canonical_public_url(self):
        row = listing()
        row["title"] = "PRIVATE-SELLER-TITLE"
        row["url"] += "?contact=PRIVATE-CONTACT#PRIVATE-FRAGMENT"
        row.update({"seller": "PRIVATE-SELLER", "phone": "PRIVATE-PHONE",
                    "email": "PRIVATE-EMAIL", "account": "PRIVATE-ACCOUNT",
                    "subject": "PRIVATE-TITLE", "description": "PRIVATE-DESCRIPTION",
                    "extra": {"password": "PRIVATE-PASSWORD"}})
        payload = self.cycle({"barotem": result(row), "itembay": result()})
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("PRIVATE-", encoded)
        saved = payload["listings"][0]
        self.assertEqual(set(saved), set(listing()))
        self.assertEqual(saved["url"], "https://www.barotem.com/product/view/101")

    def test_store_rejects_untrusted_identifiers_sources_kinds_and_observation_times(self):
        invalid = []
        for field, value in (("id", "PRIVATE-SELLER"), ("id", "barotem:101?phone=123"),
                             ("id", "itembay:101"), ("source", "PRIVATE-SOURCE"),
                             ("kind", "PRIVATE-KIND"), ("observedAt", None),
                             ("observedAt", "not-a-time"),
                             ("observedAt", "2026-01-02T03:04:05")):
            row = listing(identifier=str(300 + len(invalid)))
            row[field] = value
            invalid.append(row)
        payload = self.cycle({"barotem": result(listing(), *invalid),
                              "itembay": result()})
        self.assertEqual([row["id"] for row in payload["listings"]], ["barotem:101"])
        self.assertNotIn("PRIVATE-", json.dumps(payload, ensure_ascii=False))

    def test_invalid_count_metadata_cannot_publish_nonfinite_or_negative_counts(self):
        for value in (float("nan"), float("inf"), -1, True, "PRIVATE-COUNT"):
            with self.subTest(value=value):
                metadata = result(listing(), total=value)
                metadata["pagesFetched"] = value
                metadata["rejectedCount"] = value
                payload = self.cycle({"barotem": metadata, "itembay": result()})
                state = source_record(payload, "barotem")
                self.assertIsNone(state["totalListings"])
                self.assertEqual(state["pagesFetched"], 0)
                self.assertEqual(state["rejectedCount"], 0)
                json.dumps(payload, allow_nan=False)


class ServiceTests(TemporaryStoreTest):
    def test_health_degrades_when_retained_data_ages_without_triggering_collection(self):
        self.cycle()
        now = [START]
        calls = []

        def collector(source_id, pages=3):
            calls.append(source_id)
            raise AssertionError("Health checks must not collect")

        service = PriceService(self.store, collector=collector, interval=600, pages=3,
                               utcnow=lambda: now[0], monotonic=lambda: 0.0)
        initial = service.cached_response()
        self.assertEqual(service.health()["status"], "ok")
        now[0] += timedelta(seconds=1201)
        self.assertEqual(service.health()["status"], "degraded")
        self.assertTrue(service.health()["stale"])
        self.assertEqual(service.cached_response(), initial)
        self.assertEqual(calls, [])

    def test_service_restores_cache_without_collecting_and_keeps_stable_etag(self):
        self.cycle()
        calls = []

        def collector(source_id, pages=3):
            calls.append((source_id, pages))
            raise AssertionError("A cached read must not collect")

        service = PriceService(self.store, collector=collector, interval=600, pages=3,
                               utcnow=lambda: START, monotonic=lambda: 0.0)
        first_bytes, first_etag = service.cached_response()
        self.assertEqual(json.loads(first_bytes), self.store.load_snapshot())
        self.assertEqual(service.cached_response(), (first_bytes, first_etag))
        self.assertTrue(first_etag)
        self.assertEqual(calls, [])

    def test_run_cycle_handles_collector_failure_independently(self):
        self.cycle()
        calls = []

        def collector(source_id, pages=3):
            calls.append((source_id, pages))
            if source_id == "barotem":
                raise RuntimeError("private upstream response: PRIVATE-SECRET")
            return result(listing("itembay", "999", price=7300))

        service = PriceService(self.store, collector=collector, interval=600, pages=3,
                               utcnow=lambda: START + timedelta(seconds=600),
                               monotonic=lambda: 600.0)
        service.run_cycle()
        payload = json.loads(service.cached_response()[0])
        self.assertCountEqual(calls, [("barotem", 3), ("itembay", 3)])
        self.assertEqual([row["id"] for row in payload["listings"]],
                         ["barotem:101", "itembay:999"])
        self.assertNotIn("PRIVATE-SECRET", json.dumps(payload))


class SchedulerTests(unittest.TestCase):
    def test_monotonic_schedule_stays_fixed_and_skips_elapsed_slots_after_slow_cycle(self):
        clock = [0.0]
        starts, deadlines, waits, active = [], [], [], []
        durations = iter((75, 700, 10))

        class FakeService:
            interval = 600

            def monotonic(self):
                return clock[0]

            def utcnow(self):
                raise AssertionError("Scheduling must use monotonic time")

            def run_cycle(self, scheduled_start=None):
                if active:
                    raise AssertionError("Cycles overlapped")
                active.append(True)
                deadlines.append(scheduled_start)
                starts.append(clock[0])
                clock[0] += next(durations)
                active.pop()

        class FakeStopEvent:
            stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, seconds):
                waits.append(seconds)
                clock[0] += seconds
                self.stopped = len(waits) == 3
                return self.stopped

        PriceService.scheduler_loop(FakeService(), FakeStopEvent())
        self.assertEqual(deadlines, [0.0, 600.0, 1800.0])
        self.assertEqual(starts, deadlines)
        self.assertEqual(waits, [525.0, 500.0, 590.0])
        self.assertEqual(active, [])


class HTTPTests(TemporaryStoreTest):
    def setUp(self):
        super().setUp()
        self.cycle()
        self.calls = []

        def collector(source_id, pages=3):
            self.calls.append((source_id, pages))
            raise AssertionError("GET and HEAD must not collect")

        self.service = PriceService(self.store, collector=collector, interval=600,
                                    pages=3, utcnow=lambda: START,
                                    monotonic=lambda: 0.0)
        self.static_root = self.data_dir / "public"
        self.static_root.mkdir()
        (self.static_root / "market.html").write_text("MARKET-PAGE", encoding="utf-8")
        (self.static_root / "index.html").write_text("INDEX-PAGE", encoding="utf-8")
        (self.static_root / "secret.py").write_text("PRIVATE-PYTHON", encoding="utf-8")
        (self.static_root / "prices.sqlite3").write_text("PRIVATE-DATABASE", encoding="utf-8")
        (self.static_root / "private.json").write_text("PRIVATE-JSON", encoding="utf-8")
        (self.data_dir / "outside.txt").write_text("PRIVATE-OUTSIDE", encoding="utf-8")
        (self.static_root / "assets").mkdir()
        (self.static_root / ".market-data").mkdir()
        hidden_database = self.static_root / ".market-data" / "prices.sqlite3"
        hidden_database.write_text("PRIVATE-SYMLINK-DATABASE", encoding="utf-8")
        (self.static_root / "assets" / "leak.png").symlink_to(hidden_database)
        self.server = create_server(self.service, host="127.0.0.1", port=0,
                                    static_root=self.static_root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def request(self, path, *, method="GET", headers=None, body=None):
        request = Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def test_get_head_and_conditional_get_share_cached_json_without_refresh(self):
        initial = self.service.cached_response()
        status, headers, body = self.request("/api/prices")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), json.loads(initial[0]))
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(headers["ETag"], initial[1])
        status, head_headers, head_body = self.request("/api/prices", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers["ETag"], headers["ETag"])
        self.assertEqual(head_headers["Content-Length"], str(len(body)))
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                status, _, body = self.request("/api/prices", method=method,
                                               headers={"If-None-Match": headers["ETag"]})
                self.assertEqual(status, 304)
                self.assertEqual(body, b"")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.cached_response(), initial)

    def test_static_allowlist_blocks_database_python_and_path_traversal(self):
        status, _, body = self.request("/market.html")
        self.assertEqual((status, body), (200, b"MARKET-PAGE"))
        for path in ("/secret.py", "/prices.sqlite3", "/private.json", "/market/store.py",
                     "/.git/config", "/../outside.txt", "/%2e%2e/outside.txt",
                     "/assets/../../outside.txt", "/assets/%2e%2e/%2e%2e/outside.txt",
                     "/%2f..%2foutside.txt", "/assets/leak.png"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertGreaterEqual(status, 400)
                self.assertNotIn(b"PRIVATE-", body)
        self.assertEqual(self.calls, [])

    def test_unsupported_routes_and_mutation_methods_cannot_refresh(self):
        initial = self.service.cached_response()
        for path in ("/api/refresh", "/api/missing", "/arbitrary-file"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertGreaterEqual(status, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, _, _ = self.request("/api/prices", method=method, body=b"{}")
                self.assertGreaterEqual(status, 400)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.cached_response(), initial)


if __name__ == "__main__":
    unittest.main()

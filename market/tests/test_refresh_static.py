"""Offline checks for restoring published history and refreshing a static feed."""

from __future__ import annotations

import copy
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from market.store import Store
from market.tests.test_service import (START, fixture_results, listing, result,
                                       source_record)
from scripts.refresh_static import fetch_previous, refresh
import scripts.refresh_static as refresh_module


class FakeResponse(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}
        self.read_limits = []

    def read(self, limit=-1):
        self.read_limits.append(limit)
        return super().read(limit)


class StaticRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        origin = Store(self.root / "origin", interval_seconds=600, pages_per_source=3)
        origin.apply_cycle(fixture_results(), now=START,
                           next_update_at=START + timedelta(seconds=600))
        self.previous = origin.apply_cycle(fixture_results(),
                                           now=START + timedelta(seconds=600),
                                           next_update_at=START + timedelta(seconds=1200))
        self.store = Store(self.root / "seeded", interval_seconds=600, pages_per_source=3)
        self.now = START + timedelta(seconds=1200)

    def histories(self, payload):
        return {server["name"]: server["history"] for server in payload["servers"]}

    def test_seed_preserves_original_timestamps_and_price_history(self):
        seeded = self.store.seed_snapshot(copy.deepcopy(self.previous))
        self.assertEqual(seeded["generatedAt"], self.previous["generatedAt"])
        self.assertEqual(seeded["nextUpdateAt"], self.previous["nextUpdateAt"])
        self.assertEqual(seeded["lastSuccessfulUpdateAt"], self.previous["lastSuccessfulUpdateAt"])
        self.assertEqual(seeded["listings"], self.previous["listings"])
        self.assertEqual(self.histories(seeded), self.histories(self.previous))
        for source_id in ("barotem", "itembay"):
            with self.subTest(source=source_id):
                self.assertEqual(source_record(seeded, source_id)["updatedAt"],
                                 source_record(self.previous, source_id)["updatedAt"])
        self.assertEqual(self.store.load_snapshot(), seeded)

    def test_seed_preserves_older_failed_source_timestamp_and_status(self):
        origin = Store(self.root / "origin", interval_seconds=600, pages_per_source=3)
        previous = origin.apply_cycle({"barotem": RuntimeError("offline"),
                                       "itembay": result(listing("itembay", "999", price=7300))},
                                      now=self.now,
                                      next_update_at=self.now + timedelta(seconds=600))
        source_record(previous, "barotem")["error"] = "PRIVATE-OLD-ERROR"
        seeded = self.store.seed_snapshot(previous)
        barotem = source_record(seeded, "barotem")
        self.assertEqual(barotem["status"], "error")
        self.assertEqual(barotem["updatedAt"], "2026-01-02T03:14:05Z")
        self.assertNotEqual(barotem["updatedAt"], seeded["generatedAt"])
        self.assertEqual(source_record(seeded, "itembay")["updatedAt"], seeded["generatedAt"])
        self.assertEqual(self.histories(seeded), self.histories(previous))
        self.assertNotIn("PRIVATE-", json.dumps(seeded, ensure_ascii=False))

    def test_seed_rejects_missing_feed_timestamps_instead_of_inventing_import_time(self):
        for field in ("generatedAt", "nextUpdateAt"):
            previous = copy.deepcopy(self.previous)
            previous.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.store.seed_snapshot(previous)
                self.assertIsNone(self.store.load_snapshot())

    def test_repeated_seed_does_not_duplicate_history(self):
        first = self.store.seed_snapshot(copy.deepcopy(self.previous))
        second = self.store.seed_snapshot(copy.deepcopy(self.previous))
        self.assertEqual(first, second)
        with sqlite3.connect(self.store.db_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        self.assertEqual(count, sum(len(history) for history in self.histories(first).values()))

    def test_seed_drops_invalid_prices_and_history_and_strips_private_fields(self):
        previous = copy.deepcopy(self.previous)
        previous["seller"] = "PRIVATE-ROOT-IDENTITY"
        previous["listings"][0].update({"seller": "PRIVATE-SELLER",
                                         "title": "PRIVATE-TITLE",
                                         "url": previous["listings"][0]["url"] + "?phone=PRIVATE-PHONE"})
        invalid = listing(identifier="666")
        invalid["unitPrice"] = float("nan")
        previous["listings"].append(invalid)
        for source in previous["sources"]:
            source["warnings"] = ["PRIVATE-WARNING"]
            source["error"] = "PRIVATE-ERROR"
            source["phone"] = "PRIVATE-SOURCE-PHONE"
        valid_history = copy.deepcopy(previous["servers"][0]["history"])
        previous["servers"][0]["history"][0]["seller"] = "PRIVATE-HISTORY-IDENTITY"
        for at, value, kind in (("not-a-time", 6200, "ask"),
                                ("2026-01-02T03:16:05Z", float("nan"), "ask"),
                                ("2026-01-02T03:17:05Z", float("inf"), "ask"),
                                ("2026-01-02T03:18:05Z", -1, "ask"),
                                ("2026-01-02T03:19:05Z", 6200, "PRIVATE-KIND")):
            previous["servers"][0]["history"].append({"at": at, "value": value, "kind": kind})
        seeded = self.store.seed_snapshot(previous)
        encoded = json.dumps(seeded, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("PRIVATE-", encoded)
        self.assertEqual([row["id"] for row in seeded["listings"]],
                         [row["id"] for row in self.previous["listings"]])
        self.assertEqual(seeded["listings"][0]["url"], self.previous["listings"][0]["url"])
        self.assertEqual(seeded["servers"][0]["history"], valid_history)

    def test_seed_rejects_wrong_schema_and_snapshots_without_usable_prices(self):
        wrong_schema = copy.deepcopy(self.previous)
        wrong_schema["schemaVersion"] = 2
        no_prices = copy.deepcopy(self.previous)
        no_prices["listings"] = []
        invalid_prices = copy.deepcopy(self.previous)
        for row in invalid_prices["listings"]:
            row["quantity"] = 0
        for previous in (wrong_schema, no_prices, invalid_prices):
            with self.subTest(previous=previous["schemaVersion"], rows=len(previous["listings"])):
                with self.assertRaises(ValueError):
                    self.store.seed_snapshot(previous)
                self.assertIsNone(self.store.load_snapshot())

    def test_failed_refresh_after_seed_retains_old_listings_timestamps_and_history(self):
        prior = self.store.seed_snapshot(copy.deepcopy(self.previous))
        payload = self.store.apply_cycle({"barotem": RuntimeError("PRIVATE-SOURCE-ERROR"),
                                         "itembay": RuntimeError("PRIVATE-SOURCE-ERROR")},
                                        now=self.now,
                                        next_update_at=self.now + timedelta(seconds=600))
        self.assertEqual(payload["listings"], prior["listings"])
        self.assertEqual(self.histories(payload), self.histories(prior))
        self.assertEqual(payload["lastSuccessfulUpdateAt"], prior["lastSuccessfulUpdateAt"])
        self.assertNotIn("PRIVATE-", json.dumps(payload, ensure_ascii=False))
        for source_id in ("barotem", "itembay"):
            with self.subTest(source=source_id):
                state = source_record(payload, source_id)
                self.assertEqual(state["status"], "error")
                self.assertEqual(state["updatedAt"], source_record(prior, source_id)["updatedAt"])

    def test_refresh_without_any_prior_prices_rejects_total_source_failure(self):
        output = self.root / "output" / "prices.json"
        fetches, collections = [], []

        def fetcher(url):
            fetches.append(url)
            return None

        def collector(source_id, pages=3):
            collections.append((source_id, pages))
            raise RuntimeError("PRIVATE-UPSTREAM-ERROR")

        with self.assertRaises(RuntimeError):
            refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                    self.root / "fresh-run", output, collector=collector,
                    fetcher=fetcher, now=self.now)
        self.assertEqual(len(fetches), 1)
        self.assertCountEqual(collections, [("barotem", 3), ("itembay", 3)])
        self.assertFalse(output.exists())

    def test_refresh_total_outage_exports_retained_prices_with_failed_source_status(self):
        output = self.root / "output" / "prices.json"
        calls = []

        def collector(source_id, pages=3):
            calls.append((source_id, pages))
            raise RuntimeError("PRIVATE-UPSTREAM-ERROR")

        payload = refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                          self.root / "outage-run", output, collector=collector,
                          fetcher=lambda url: copy.deepcopy(self.previous), now=self.now)
        self.assertCountEqual(calls, [("barotem", 3), ("itembay", 3)])
        self.assertEqual(payload["listings"], self.previous["listings"])
        self.assertEqual(self.histories(payload), self.histories(self.previous))
        self.assertTrue(payload["stale"])
        self.assertEqual(json.loads(output.read_bytes()), payload)
        self.assertNotIn("PRIVATE-", output.read_text(encoding="utf-8"))
        for source_id in ("barotem", "itembay"):
            with self.subTest(source=source_id):
                state = source_record(payload, source_id)
                self.assertEqual(state["status"], "error")
                self.assertEqual(state["updatedAt"], source_record(self.previous, source_id)["updatedAt"])

    def test_refresh_one_source_success_replaces_only_that_source_and_appends_history(self):
        output = self.root / "output" / "prices.json"

        def collector(source_id, pages=3):
            if source_id == "barotem":
                raise RuntimeError("offline")
            return result(listing("itembay", "999", price=7300))

        payload = refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                          self.root / "partial-run", output, collector=collector,
                          fetcher=lambda url: copy.deepcopy(self.previous), now=self.now)
        self.assertEqual([row for row in payload["listings"] if row["source"] == "barotem"],
                         [row for row in self.previous["listings"] if row["source"] == "barotem"])
        self.assertEqual([row["id"] for row in payload["listings"] if row["source"] == "itembay"],
                         ["itembay:999"])
        self.assertEqual(source_record(payload, "itembay")["status"], "ok")
        self.assertEqual(source_record(payload, "itembay")["updatedAt"], "2026-01-02T03:24:05Z")
        previous_history = next(iter(self.histories(self.previous).values()))
        current_history = next(iter(self.histories(payload).values()))
        self.assertEqual(current_history[:-1], previous_history)
        self.assertEqual(current_history[-1]["value"], 7300)
        self.assertEqual(json.loads(output.read_bytes()), payload)

    def test_unusable_previous_fetch_does_not_block_successful_fresh_collection(self):
        output = self.root / "output" / "prices.json"

        def fetcher(url):
            raise refresh_module.PreviousSnapshotError("Published snapshot unavailable")

        payload = refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                          self.root / "without-prior", output,
                          collector=lambda source_id, pages=3: fixture_results()[source_id],
                          fetcher=fetcher, now=self.now)
        self.assertEqual(len(payload["listings"]), 3)
        self.assertFalse(payload["stale"])
        self.assertEqual(json.loads(output.read_bytes()), payload)


class FetchPreviousTests(unittest.TestCase):
    url = "https://example.github.io/Lin-Cl-Uni/test/data/prices.json"

    def test_fetch_uses_bounded_verified_https_with_timeout(self):
        data = {"schemaVersion": 1, "listings": []}
        response = FakeResponse(json.dumps(data).encode("utf-8"))
        with patch.object(refresh_module, "build_opener") as build_opener:
            opener = build_opener.return_value
            opener.open.return_value = response
            self.assertEqual(fetch_previous(self.url), data)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)
        self.assertEqual(response.read_limits, [1024 * 1024 + 1])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, self.url)
        self.assertIsInstance(build_opener.call_args.args[0],
                              refresh_module._SameSiteHTTPSRedirects)

    def test_non_page_https_hosts_credentials_and_query_inputs_never_open_network(self):
        for url in ("http://example.github.io/test/data/prices.json",
                    "https://evil.example/test/data/prices.json",
                    "https://127.0.0.1/test/data/prices.json",
                    "https://github.io/test/data/prices.json",
                    "https://example.github.io.evil.example/test/data/prices.json",
                    "https://user:password@example.github.io/test/data/prices.json",
                    self.url + "?token=PRIVATE-TOKEN", self.url + "#fragment"):
            with self.subTest(url=url), patch.object(refresh_module, "build_opener") as opener:
                with self.assertRaises(refresh_module.PreviousSnapshotError):
                    fetch_previous(url)
                opener.assert_not_called()

    def test_missing_previous_is_expected_but_other_http_and_network_errors_fail(self):
        for error, expected_none in ((HTTPError(self.url, 404, "Not found", {}, None), True),
                                     (HTTPError(self.url, 503, "Unavailable", {}, None), False),
                                     (URLError("Connection failed"), False)):
            with self.subTest(error=type(error).__name__, missing=expected_none):
                with patch.object(refresh_module, "build_opener") as build_opener:
                    build_opener.return_value.open.side_effect = error
                    if expected_none:
                        self.assertIsNone(fetch_previous(self.url))
                    else:
                        with self.assertRaises(refresh_module.PreviousSnapshotError):
                            fetch_previous(self.url)

    def test_oversized_invalid_json_and_wrong_schema_responses_are_rejected(self):
        for body in (b"x" * (1024 * 1024 + 1), b"not-json",
                     b'{"schemaVersion":2,"listings":[]}', b"[]"):
            with self.subTest(size=len(body)), patch.object(refresh_module, "build_opener") as build_opener:
                build_opener.return_value.open.return_value = FakeResponse(body)
                with self.assertRaises(refresh_module.PreviousSnapshotError):
                    fetch_previous(self.url)

    def test_redirects_remain_on_same_https_host(self):
        handler = refresh_module._SameSiteHTTPSRedirects()
        request = Request(self.url)
        redirect = handler.redirect_request(request, None, 302, "Found", {},
                                             "https://example.github.io/new/test/data/prices.json")
        self.assertEqual(redirect.full_url, "https://example.github.io/new/test/data/prices.json")
        for url in ("http://example.github.io/new/test/data/prices.json",
                    "https://other.github.io/new/test/data/prices.json",
                    "https://example.github.io.evil.example/new/test/data/prices.json"):
            with self.subTest(url=url):
                with self.assertRaises(refresh_module.PreviousSnapshotError):
                    handler.redirect_request(request, None, 302, "Found", {}, url)


if __name__ == "__main__":
    unittest.main()

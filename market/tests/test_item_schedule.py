"""Offline checks for hourly items alongside ten-minute currency refreshes."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from market.server import PriceService
from market.store import Store, timestamp
from market.tests.test_service import START, fixture_results, listing, result, source_record
from scripts.refresh_static import refresh


def item_results():
    from market.item_catalog import get_item, public_catalog

    entry = get_item(public_catalog()["entries"][0]["id"])
    rows = {}
    for source_id, identifier in (("barotem", "401"), ("itembay", "501")):
        row = listing(source_id, identifier, price=20000, quantity=1)
        row.update({"itemId": entry["id"], "itemName": entry["name"],
                    "enchant": None, "blessing": "unknown", "unitPrice": 20000})
        rows[source_id] = result(row)
        rows[source_id].update({"rawCount": 4, "eligibleTotal": 1,
                                "excludedCounts": {"unmapped": 2, "ambiguous": 1, "invalid": 0}})
    return rows


class ItemScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "state", interval_seconds=600,
                           item_interval_seconds=3600, pages_per_source=3)
        self.now = START
        self.currency_calls = []
        self.item_calls = []
        self.fail_items = False

    def currency_collector(self, source_id, pages=3):
        self.currency_calls.append((self.now, source_id, pages))
        return copy.deepcopy(fixture_results()[source_id])

    def item_collector(self, source_id, pages=3):
        self.item_calls.append((self.now, source_id, pages))
        if self.fail_items:
            raise RuntimeError("PRIVATE-ITEM-ERROR")
        return copy.deepcopy(item_results()[source_id])

    def service(self, store=None):
        return PriceService(store or self.store, collector=self.currency_collector,
                            item_collector=self.item_collector, interval=600,
                            item_interval=3600, pages=3, utcnow=lambda: self.now,
                            monotonic=lambda: (self.now - START).total_seconds())

    def test_currency_ticks_do_not_collect_items_again_before_the_hour(self):
        service = self.service()
        first = service.run_cycle()
        self.assertEqual(len(self.item_calls), 2)
        for source_id in ("barotem", "itembay"):
            state = source_record(first["items"], source_id)
            self.assertEqual(state["rawCount"], 4)
            self.assertEqual(state["unmappedCount"], 2)
            self.assertEqual(state["ambiguousCount"], 1)
        for seconds in (600, 1200, 1800, 2400, 3000, 3599):
            self.now = START + timedelta(seconds=seconds)
            current = service.run_cycle()
            self.assertEqual(current["items"], first["items"])
            self.assertEqual(len(self.item_calls), 2)
        self.now = START + timedelta(seconds=3600)
        current = service.run_cycle()
        self.assertEqual(len(self.currency_calls), 16)
        self.assertEqual(len(self.item_calls), 4)
        self.assertNotEqual(current["items"]["generatedAt"], first["items"]["generatedAt"])
        self.assertEqual(current["intervalSeconds"], 600)
        self.assertEqual(current["items"]["intervalSeconds"], 3600)

    def test_restart_and_health_reads_keep_the_existing_item_deadline(self):
        first = self.service().run_cycle()
        self.now = START + timedelta(seconds=1800)
        restarted_store = Store(self.root / "state", interval_seconds=600,
                                item_interval_seconds=3600, pages_per_source=3)
        service = self.service(restarted_store)
        cached_before = service.cached_response()
        for _ in range(3):
            service.cached_response()
            health = service.health()
            self.assertEqual(health["items"]["intervalSeconds"], 3600)
            self.assertEqual(health["items"]["generatedAt"], first["items"]["generatedAt"])
        self.assertEqual(service.cached_response(), cached_before)
        self.assertEqual(len(self.item_calls), 2)
        current = service.run_cycle()
        self.assertEqual(current["items"], first["items"])
        self.assertEqual(len(self.item_calls), 2)

    def test_collection_duration_does_not_push_the_hourly_deadline_to_next_currency_tick(self):
        def slow_currency(source_id, pages=3):
            collected = self.currency_collector(source_id, pages=pages)
            self.now += timedelta(seconds=10)
            return collected

        def slow_items(source_id, pages=3):
            collected = self.item_collector(source_id, pages=pages)
            self.now += timedelta(seconds=10)
            return collected

        service = PriceService(self.store, collector=slow_currency, item_collector=slow_items,
                               interval=600, item_interval=3600, pages=3,
                               utcnow=lambda: self.now,
                               monotonic=lambda: (self.now - START).total_seconds())
        first = service.run_cycle()
        self.assertEqual(first["items"]["generatedAt"], timestamp(START + timedelta(seconds=40)))
        self.assertEqual(first["items"]["nextUpdateAt"], timestamp(START + timedelta(seconds=3600)))
        restored = Store(self.root / "duration-restart", item_interval_seconds=3600)
        imported = restored.seed_snapshot(copy.deepcopy(first))
        self.assertEqual(imported["items"]["nextUpdateAt"], first["items"]["nextUpdateAt"])
        self.assertTrue(restored.items_due(START + timedelta(seconds=3600)))
        self.now = START + timedelta(seconds=3600)
        second = service.run_cycle()
        self.assertEqual(len(self.item_calls), 4)
        self.assertEqual(second["items"]["nextUpdateAt"], timestamp(START + timedelta(seconds=7200)))

    def test_failed_item_attempt_retains_prices_and_waits_another_hour(self):
        service = self.service()
        first = service.run_cycle()
        self.fail_items = True
        self.now = START + timedelta(seconds=3600)
        failed = service.run_cycle()
        self.assertEqual(failed["items"]["listings"], first["items"]["listings"])
        self.assertEqual(failed["items"]["lastSuccessfulUpdateAt"], first["items"]["lastSuccessfulUpdateAt"])
        self.assertNotEqual(failed["items"]["generatedAt"], first["items"]["generatedAt"])
        self.assertTrue(failed["items"]["stale"])
        for source_id in ("barotem", "itembay"):
            self.assertEqual(source_record(failed["items"], source_id)["updatedAt"],
                             source_record(first["items"], source_id)["updatedAt"])
        self.now = START + timedelta(seconds=4200)
        retained = service.run_cycle()
        self.assertEqual(retained["items"], failed["items"])
        self.assertEqual(len(self.item_calls), 4)
        self.now = START + timedelta(seconds=7200)
        service.run_cycle()
        self.assertEqual(len(self.item_calls), 6)
        self.assertNotIn("PRIVATE-", json.dumps(retained))

    def test_injected_currency_collector_does_not_enable_real_item_network_calls(self):
        with patch("market.collectors.collect_items") as real_item_collector:
            service = PriceService(self.store, collector=self.currency_collector,
                                   interval=600, utcnow=lambda: self.now,
                                   monotonic=lambda: 0.0)
            service.run_cycle()
            real_item_collector.assert_not_called()
        self.assertEqual(service.health()["items"]["status"], "disabled")

    def test_static_refresh_restores_hourly_state_in_a_fresh_runner(self):
        previous = self.service().run_cycle()
        self.now = START + timedelta(seconds=600)
        output = self.root / "export" / "prices.json"
        current = refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                          self.root / "fresh-runner", output,
                          collector=self.currency_collector, item_collector=self.item_collector,
                          fetcher=lambda url: copy.deepcopy(previous), now=self.now)
        self.assertEqual(len(self.item_calls), 2)
        for key, value in previous["items"].items():
            if key != "sources":
                self.assertEqual(current["items"][key], value)
        for source_id in ("barotem", "itembay", "itemmania"):
            before = {key: value for key, value in source_record(previous["items"], source_id).items()
                      if key != "warnings"}
            after = {key: value for key, value in source_record(current["items"], source_id).items()
                     if key != "warnings"}
            self.assertEqual(after, before)
        self.assertEqual(json.loads(output.read_bytes()), current)

    def test_static_refresh_adds_items_to_an_old_currency_only_snapshot(self):
        previous = self.store.apply_cycle(fixture_results(), now=START)
        self.assertNotIn("items", previous)
        self.now = START + timedelta(seconds=600)
        current = refresh("https://example.github.io/Lin-Cl-Uni/test/data/prices.json",
                          self.root / "legacy-runner", self.root / "legacy-prices.json",
                          collector=self.currency_collector, item_collector=self.item_collector,
                          fetcher=lambda url: copy.deepcopy(previous), now=self.now)
        self.assertEqual(current["schemaVersion"], 1)
        self.assertEqual(len(current["items"]["listings"]), 2)
        self.assertEqual(len(self.item_calls), 2)


if __name__ == "__main__":
    unittest.main()

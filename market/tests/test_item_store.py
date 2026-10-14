"""Item prices must remain comparable, anonymous and independently durable."""

import copy
import json
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from market.item_store import normalize_item_listing
from market.store import Store
from market.tests.test_service import START, START_TEXT, fixture_results, result


ENTRIES = {
    "test-sword": {"id": "test-sword", "name": "시험용 검", "enhanceable": True},
    "test-scroll": {"id": "test-scroll", "name": "시험용 주문서", "enhanceable": False},
}


def item_row(identifier="901", *, source="barotem", item_id="test-sword", enchant=None,
             blessing="unknown", server="데포로쥬", kind="ask", price=180000, quantity=1):
    return {"id": source + ":" + identifier, "source": source, "server": server,
            "kind": kind, "itemId": item_id, "itemName": ENTRIES[item_id]["name"],
            "enchant": enchant, "blessing": blessing, "unitPrice": price / quantity,
            "priceKRW": price, "quantity": quantity, "observedAt": START_TEXT,
            "url": "https://www.barotem.com/product/view/" + identifier if source == "barotem" else
                   "https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=" + identifier,
            "title": "discard raw subject", "seller": "private-person", "phone": "010-private"}


class ItemStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        fake_catalog = patch("market.item_catalog.get_item", side_effect=lambda item_id: ENTRIES.get(item_id))
        fake_catalog.start()
        self.addCleanup(fake_catalog.stop)

    def cycle(self, rows=None, now=START):
        return self.store.apply_item_cycle({"barotem": result(*(rows if rows is not None else [item_row()])),
                                           "itembay": result()}, now=now)

    def test_price_is_per_item_and_raw_subject_identity_are_dropped(self):
        row = normalize_item_listing(item_row(price=30000, quantity=3), "barotem")
        self.assertEqual(row["unitPrice"], 10000)
        self.assertEqual(row["title"], "시험용 검")
        self.assertNotIn("seller", row)
        self.assertNotIn("phone", row)
        self.assertNotIn("discard raw", json.dumps(row))

    def test_server_enchant_blessing_and_item_identity_never_merge(self):
        rows = [item_row("901", enchant=7), item_row("902", enchant=7, price=220000),
                item_row("903", enchant=8), item_row("904", enchant=7, blessing="normal"),
                item_row("905", enchant=7, blessing="blessed"),
                item_row("906", enchant=7, server="켄라우헬"),
                item_row("907", item_id="test-scroll"), item_row("908")]
        payload = self.cycle(rows)
        self.assertEqual(len(payload["groups"]), 7)
        matching = next(group for group in payload["groups"] if group["server"] == "데포로쥬" and
                        group["enchant"] == 7 and group["blessing"] == "unknown")
        self.assertEqual(matching["askMedian"], 200000)
        self.assertEqual(matching["listingCount"], 2)

    def test_completed_and_ask_statistics_are_separate(self):
        payload = self.cycle([item_row("901", price=200000), item_row("902", kind="completed", price=170000)])
        group = payload["groups"][0]
        self.assertEqual(group["askMedian"], 200000)
        self.assertEqual(group["completedMedian"], 170000)

    def test_invalid_identity_price_and_variant_cannot_cross_boundary(self):
        mutations = [{"itemId": "unregistered"}, {"itemName": "arbitrary seller title"},
                     {"unitPrice": 180000 * 1000000}, {"quantity": 1.5},
                     {"enchant": True}, {"enchant": -1}, {"enchant": 16},
                     {"blessing": "unknown value"}, {"priceKRW": float("nan")},
                     {"itemId": "test-scroll", "itemName": "시험용 주문서", "enchant": 7}]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize_item_listing({**item_row(), **mutation}, "barotem")

    def test_currency_update_and_restart_keep_item_timestamp_and_values(self):
        original = self.cycle()
        self.store.apply_cycle(fixture_results(), now=START)
        updated = self.store.apply_cycle(fixture_results(), now=START + timedelta(minutes=10))
        self.assertEqual(updated["items"], original)
        self.assertEqual(Store(self.temporary.name).load_snapshot()["items"], original)

    def test_failed_item_source_retains_its_last_good_rows_and_age(self):
        first = self.cycle()
        later = self.store.apply_item_cycle({"barotem": RuntimeError("private-person"), "itembay": result()},
                                           now=START + timedelta(hours=1))
        self.assertEqual(later["listings"], first["listings"])
        source = next(source for source in later["sources"] if source["id"] == "barotem")
        self.assertEqual(source["updatedAt"], START_TEXT)
        self.assertEqual(source["status"], "error")
        self.assertNotIn("private-person", json.dumps(later))

    def test_safe_seed_rebuilds_groups_and_catalog_and_preserves_hourly_age(self):
        items = self.cycle()
        previous = self.store.apply_cycle(fixture_results(), now=START)
        previous["items"] = items
        previous["items"]["groups"] = [{"itemName": "private-person", "askMedian": -4}]
        previous["items"]["catalog"] = {"entries": [{"name": "private-person"}]}
        previous["items"]["listings"][0]["seller"] = "private-person"
        with tempfile.TemporaryDirectory() as directory:
            new_store = Store(directory)
            imported = new_store.seed_snapshot(copy.deepcopy(previous))
            self.assertEqual(imported["items"]["generatedAt"], START_TEXT)
            self.assertEqual(imported["items"]["groups"][0]["askMedian"], 180000)
            self.assertFalse(new_store.items_due(START + timedelta(minutes=59)))
            self.assertTrue(new_store.items_due(START + timedelta(hours=1)))
            self.assertNotIn("private-person", json.dumps(imported))

    def test_initial_missing_mapping_is_visible_empty_without_invented_prices(self):
        data = {**result(), "unmappedCount": 10, "rawCount": 10, "rejectedCount": 10}
        payload = self.store.apply_item_cycle({"barotem": data, "itembay": result()}, now=START)
        self.assertEqual(payload["listings"], [])
        self.assertEqual(payload["groups"], [])
        self.assertEqual(payload["sources"][0]["unmappedCount"], 10)
        self.assertEqual(payload["sources"][0]["status"], "ok")

    def test_changed_mapping_is_collected_before_the_old_hourly_deadline(self):
        original = self.cycle()
        self.assertFalse(self.store.items_due(START + timedelta(minutes=10)))
        with patch("market.item_catalog.MAPPING_VERSION", "next-reviewed-mapping"):
            self.assertTrue(self.store.items_due(START + timedelta(minutes=10)))
            with tempfile.TemporaryDirectory() as directory:
                seeded_store = Store(directory)
                seeded_store.seed_item_snapshot(original, currency_generated_at=START_TEXT)
                self.assertTrue(seeded_store.items_due(START + timedelta(minutes=10)))

    def test_corrected_catalog_spelling_keeps_retained_price_and_observation_age(self):
        previous = self.cycle()
        corrected = {**ENTRIES["test-sword"], "name": "시험의 검"}
        with patch("market.item_catalog.get_item", return_value=corrected):
            current = self.store.apply_item_cycle({"barotem": RuntimeError("offline"), "itembay": result()},
                                                  now=START + timedelta(hours=1))
            row = current["listings"][0]
            self.assertEqual(row["itemName"], "시험의 검")
            self.assertEqual(row["unitPrice"], previous["listings"][0]["unitPrice"])
            self.assertEqual(row["observedAt"], START_TEXT)
            self.assertEqual(current["sources"][0]["updatedAt"], START_TEXT)


if __name__ == "__main__":
    unittest.main()

"""Offline tests using sanitized, real-shaped public-listing fixtures."""

import copy
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from market import collectors


OBSERVED_AT = "2026-10-14T01:00:00Z"


def barotem_row(**updates):
    # Numeric public IDs are synthetic; source-shaped price/quantity fields.
    row = {"number": "10001", "category": "2382r902", "sell_type": "sell",
           "server": "아덴", "saletype": "0", "baro_price": "1500",
           "min_cnt": "10", "work_same_cnt": "600", "saleUnitText": "만 아데나",
           "single_unit": "1만 아데나", "deal_quantity": "535만 아데나",
           "deal_price": "802,500원", "product_name": "판매자 연락처 010-0000-0000",
           "online_date": "2026-10-14 10:00:00", "unit_price": "만당 1,500원"}
    row.update(updates)
    return row


def itembay_row(**updates):
    row = {"iItemSeq": "20001", "iGameSeq": 3828, "tiItemType": 3,
           "tiSellStatus": 0, "vcServerName": "아덴", "iPrice": 650,
           "biWantQuantity": 10000, "biMinQuantity": 1000000,
           "biMaxQuantity": 5000000, "tranPrice": "65,000", "cAddType": "0",
           "iTranPrice": 0, "biTranQuantity": 0, "vcMemberID": "private-id",
           "vcNickName": "private-seller", "vcComment": "private-comment",
           "vcSubject": "판매자 연락처 010-0000-0000", "dtRegDate": "2026-10-14 10:00:00"}
    row.update(updates)
    return row


def barotem_response(*rows):
    return {"code": 200, "rows": list(rows), "pagecount": 60, "total": ""}


def itembay_response(*rows, adverts=None):
    return {"code": "0", "data": {"iTotalCount": 6002, "list": list(rows),
                                    "powerZonelist": adverts or []}}


class ParserTests(unittest.TestCase):
    def test_barotem_split_price_is_per_unit_not_minimum_total(self):
        rows, rejected = collectors.parse_barotem(barotem_response(barotem_row()), OBSERVED_AT)
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["quantity"], 100000)
        self.assertEqual(rows[0]["priceKRW"], 15000)
        self.assertEqual(rows[0]["unitPrice"], 150000)

    def test_barotem_bundle_uses_exact_total_and_quantity_not_rounded_label(self):
        row = barotem_row(saletype="1", baro_price="158000", single_unit="180만 아데나",
                          unit_price="만당 878원")
        rows, rejected = collectors.parse_barotem(barotem_response(row), OBSERVED_AT)
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["quantity"], 1800000)
        self.assertAlmostEqual(rows[0]["unitPrice"], 158000 / 1.8, places=5)
        self.assertNotEqual(rows[0]["unitPrice"], 87800)

    def test_barotem_remaining_bundle_uses_deal_quantity_and_price(self):
        row = barotem_row(baro_price="899", min_cnt="20", work_same_cnt="0",
                          deal_quantity="300만 아데나", deal_price="269,700원")
        rows, rejected = collectors.parse_barotem(barotem_response(row), OBSERVED_AT)
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["priceKRW"], 269700)
        self.assertEqual(rows[0]["quantity"], 3000000)
        self.assertEqual(rows[0]["unitPrice"], 89900)

    def test_barotem_compound_korean_quantity_and_unit_multiplier(self):
        self.assertEqual(collectors._adena_quantity("2억1,387만 아데나"), 213870000)
        row = barotem_row(saleUnitText="십만 아데나", min_cnt="2", baro_price="8000")
        rows, _ = collectors.parse_barotem(barotem_response(row), OBSERVED_AT)
        self.assertEqual(rows[0]["quantity"], 200000)
        self.assertEqual(rows[0]["unitPrice"], 80000)

    def test_itembay_asks_do_not_pair_minimum_price_with_base_quote_quantity(self):
        rows, rejected = collectors.parse_itembay(itembay_response(itembay_row()), OBSERVED_AT)
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["priceKRW"], 650)
        self.assertEqual(rows[0]["quantity"], 10000)
        self.assertEqual(rows[0]["unitPrice"], 65000)

    def test_itembay_live_dto_zero_game_identifier_is_accepted_for_pinned_game_query(self):
        rows, rejected = collectors.parse_itembay(itembay_response(itembay_row(iGameSeq=0)), OBSERVED_AT)
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["unitPrice"], 65000)

    def test_completed_trade_uses_executed_quantity_not_original_offer(self):
        row = itembay_row(tiSellStatus=3, iPrice=100000, biWantQuantity=1000000,
                          iTranPrice=124000, biTranQuantity=2000000)
        rows, rejected = collectors.parse_itembay(itembay_response(row), OBSERVED_AT, "completed")
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["kind"], "completed")
        self.assertEqual(rows[0]["unitPrice"], 62000)
        self.assertEqual(rows[0]["quantity"], 2000000)

    def test_completed_trade_never_falls_back_to_original_offer(self):
        rows, rejected = collectors.parse_itembay(
            itembay_response(itembay_row(tiSellStatus=3, iTranPrice=0, biTranQuantity=2000000)),
            OBSERVED_AT, "completed")
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 1)

    def test_invalid_numeric_values_are_rejected(self):
        invalid = [None, "", "NaN", float("nan"), float("inf"), "Infinity", -1, 0, True, "1e4", "-50"]
        for value in invalid:
            with self.subTest(value=value):
                rows, rejected = collectors.parse_itembay(
                    itembay_response(itembay_row(iPrice=value)), OBSERVED_AT)
                self.assertEqual(rows, [])
                self.assertEqual(rejected, 1)
        rows, rejected = collectors.parse_itembay(
            itembay_response(itembay_row(biWantQuantity=-1), itembay_row(iPrice=1e308, biWantQuantity=1e-300)),
            OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 2)

    def test_invalid_currency_quantity_wrong_game_and_unavailable_status_are_rejected(self):
        rows, rejected = collectors.parse_barotem(barotem_response(
            barotem_row(saletype="1", single_unit="200만 아이템"),
            barotem_row(category="another-game"), barotem_row(sell_type="buy")), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 3)
        rows, rejected = collectors.parse_itembay(itembay_response(
            itembay_row(tiSellStatus=3), itembay_row(iGameSeq=1), itembay_row(tiItemType=4)), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 3)

    def test_deduplicates_listing_ids_and_excludes_advertisements(self):
        current = itembay_row()
        rows, rejected = collectors.parse_itembay(
            itembay_response(current, copy.deepcopy(current), adverts=[itembay_row(iItemSeq="99999")]), OBSERVED_AT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rejected, 0)

    def test_records_are_strict_whitelist_without_seller_subject_or_contacts(self):
        allowed = {"id", "source", "server", "kind", "unitPrice", "priceKRW", "quantity",
                   "observedAt", "url", "title"}
        for payload, parser in [(barotem_response(barotem_row()), collectors.parse_barotem),
                                (itembay_response(itembay_row()), collectors.parse_itembay)]:
            rows, _ = parser(payload, OBSERVED_AT)
            self.assertEqual(set(rows[0]), allowed)
            self.assertNotIn("private", str(rows))
            self.assertNotIn("010-0000", str(rows))
            self.assertEqual(rows[0]["observedAt"], OBSERVED_AT)
        self.assertEqual(rows[0]["url"], "https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=20001")

    def test_bad_response_codes_or_schema_raise_source_error(self):
        for payload in [{"code": 100, "rows": []}, {"code": 200, "rows": None}, []]:
            with self.assertRaises(collectors.CollectorError):
                collectors.parse_barotem(payload, OBSERVED_AT)
        for payload in [{"code": "1", "data": {"list": []}}, {"code": "0", "data": {}}, None]:
            with self.assertRaises(collectors.CollectorError):
                collectors.parse_itembay(payload, OBSERVED_AT)


class CollectionTests(unittest.TestCase):
    def test_itembay_max_four_calls_and_dedup_across_pages_and_keep_each_kind(self):
        responses = [itembay_response(itembay_row())] * 3 + [itembay_response(
            itembay_row(tiSellStatus=3, iTranPrice=65000, biTranQuantity=1000000))]
        with patch.object(collectors, "_itembay_request", side_effect=responses) as request:
            result = collectors.collect_source("itembay")
        self.assertEqual(request.call_count, 4)
        self.assertEqual(request.call_args_list[-1].args, (1, "completed"))
        self.assertEqual(len(result["listings"]), 2)
        self.assertEqual({row["kind"] for row in result["listings"]}, {"ask", "completed"})
        self.assertEqual(result["totalListings"], 6002)
        self.assertEqual(result["pagesFetched"], 4)
        self.assertEqual(result["rejectedCount"], 0)
        self.assertTrue(result["listings"][0]["observedAt"].endswith("Z"))

    def test_failed_first_page_raises_without_automatic_retry(self):
        with patch.object(collectors, "_barotem_request", side_effect=collectors.CollectorError("blocked")) as request:
            with self.assertRaises(collectors.CollectorError):
                collectors.collect_source("barotem")
        self.assertEqual(request.call_count, 1)

    def test_nonempty_source_with_all_rejected_rows_is_failure_not_fresh_empty_data(self):
        with patch.object(collectors, "_itembay_request", return_value=itembay_response(itembay_row(iGameSeq=1))) as request:
            with self.assertRaises(collectors.CollectorError):
                collectors.collect_source("itembay")
        self.assertEqual(request.call_count, 1)

    def test_later_page_and_completed_failure_preserve_successful_ask_sample(self):
        with patch.object(collectors, "_itembay_request", side_effect=[
                itembay_response(itembay_row()), collectors.CollectorError("blocked"),
                collectors.CollectorError("blocked")]) as request:
            result = collectors.collect_source("itembay")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(result["pagesFetched"], 1)
        self.assertEqual(len(result["listings"]), 1)
        self.assertEqual(len(result["warnings"]), 4)

    def test_empty_page_stops_ask_paging_and_unknown_total_is_not_zero(self):
        with patch.object(collectors, "_barotem_request", return_value=barotem_response()) as request:
            result = collectors.collect_source("barotem")
        self.assertEqual(request.call_count, 1)
        self.assertIsNone(result["totalListings"])

    def test_page_limits_and_source_are_explicit(self):
        for pages in [0, 4, -1, True, "3"]:
            with self.assertRaises(ValueError):
                collectors.collect_source("barotem", pages)
        with self.assertRaises(ValueError):
            collectors.collect_source("itemmania")

    def test_requests_match_verified_search_paths_and_completed_filters(self):
        with patch.object(collectors, "_request_json", return_value={}) as request:
            collectors._barotem_request(2)
        self.assertEqual(request.call_args.args[0], "https://www.barotem.com/product/productTable/2382r902")
        fields = parse_qs(request.call_args.kwargs["body"].decode())
        self.assertEqual(fields["page"], ["2"])
        self.assertEqual(fields["sell"], ["sell"])
        self.assertEqual(fields["total"], ["no"])
        for kind in ["ask", "completed"]:
            with patch.object(collectors, "_request_json", return_value={}) as request:
                collectors._itembay_request(1, kind)
            query = parse_qs(urlsplit(request.call_args.args[0]).query)
            self.assertEqual(query["chkTranPossible"], ["true" if kind == "ask" else "false"])
            self.assertEqual(query["chkTranComplete"], ["true" if kind == "completed" else "false"])


class TransportTests(unittest.TestCase):
    def test_connection_http_and_non_json_failures_are_safe(self):
        with patch.object(collectors, "build_opener") as opener:
            for error in [URLError("private details"), HTTPError("https://source", 429, "private details", {}, None)]:
                opener.return_value.open.side_effect = error
                with self.assertRaises(collectors.CollectorError) as result:
                    collectors._request_json("https://www.itembay.com/source", referer="https://www.itembay.com/")
                self.assertNotIn("private details", str(result.exception))
            opener.return_value.open.side_effect = None
            opener.return_value.open.return_value = io.BytesIO(b"<html>login or error</html>")
            with self.assertRaises(collectors.CollectorError):
                collectors._request_json("https://www.itembay.com/source", referer="https://www.itembay.com/")

    def test_response_size_and_timeout_are_bounded(self):
        with patch.object(collectors, "MAX_RESPONSE_BYTES", 32), patch.object(collectors, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"x" * 33)
            with self.assertRaises(collectors.CollectorError):
                collectors._request_json("https://www.itembay.com/source", referer="https://www.itembay.com/")
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 15)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("X-requested-with"), "XMLHttpRequest")

    def test_redirect_rejects_http_downgrade_and_another_host(self):
        redirect = collectors._SameSiteHTTPSRedirects()
        request = collectors.Request("https://www.itembay.com/source")
        for destination in ["http://www.itembay.com/source", "https://another-host.example/source"]:
            with self.assertRaises(collectors.CollectorError):
                redirect.redirect_request(request, None, 302, "", {}, destination)


ITEM_MATCH = {"itemId": "lc-fire-sword", "itemName": "화염의 검",
              "enchant": 8, "blessing": "unknown", "mappingVersion": "test-v1"}


def barotem_item_row(**updates):
    values = {"category": "2381r870", "saletype": "1", "baro_price": "180000",
              "min_cnt": "1", "work_same_cnt": "1", "saleUnitText": " 개",
              "single_unit": "1 개", "product_name": "8화염의검 판매"}
    values.update(updates)
    return barotem_row(**values)


def itembay_item_row(**updates):
    values = {"tiItemType": 4, "iPrice": 180000, "biWantQuantity": 1,
              "biMinQuantity": 1, "biMaxQuantity": 1, "cAddType": "2",
              "tranPrice": "180,000", "vcSubject": "8화염의검 판매"}
    values.update(updates)
    return itembay_row(**values)


class ItemParserTests(unittest.TestCase):
    def setUp(self):
        self.matcher = patch.object(collectors, "_catalog_match", return_value=("mapped", copy.deepcopy(ITEM_MATCH)))
        self.match = self.matcher.start()
        self.addCleanup(self.matcher.stop)

    def test_item_price_is_one_item_not_one_million_currency(self):
        rows, counts = collectors.parse_barotem_items(barotem_response(barotem_item_row()), OBSERVED_AT)
        self.assertEqual(rows[0]["unitPrice"], 180000)
        self.assertEqual(rows[0]["itemId"], "lc-fire-sword")
        self.assertEqual(rows[0]["enchant"], 8)
        self.assertEqual(rows[0]["blessing"], "unknown")
        self.assertEqual(counts, {"unmapped": 0, "ambiguous": 0, "invalid": 0})

    def test_same_item_multiple_quantity_total_is_divided_and_passed_to_catalog(self):
        rows, _ = collectors.parse_barotem_items(barotem_response(
            barotem_item_row(single_unit="2 개", baro_price="360000")), OBSERVED_AT)
        self.assertEqual(rows[0]["unitPrice"], 180000)
        self.assertEqual(rows[0]["quantity"], 2)
        self.assertEqual(self.match.call_args.args, ("8화염의검 판매", 2))

    def test_split_item_quote_uses_minimum_quantity_and_total(self):
        rows, _ = collectors.parse_barotem_items(barotem_response(
            barotem_item_row(saletype="0", min_cnt="2", work_same_cnt="10", baro_price="5000")), OBSERVED_AT)
        self.assertEqual(rows[0]["unitPrice"], 5000)
        self.assertEqual(rows[0]["quantity"], 2)
        self.assertEqual(rows[0]["priceKRW"], 10000)

    def test_itembay_completed_price_uses_executed_quantity(self):
        rows, _ = collectors.parse_itembay_items(itembay_response(itembay_item_row(
            tiSellStatus=3, iPrice=180000, biWantQuantity=1, iTranPrice=320000, biTranQuantity=2)),
            OBSERVED_AT, "completed")
        self.assertEqual(rows[0]["unitPrice"], 160000)
        self.assertEqual(rows[0]["priceKRW"], 320000)
        self.assertEqual(rows[0]["kind"], "completed")

    def test_itembay_current_price_uses_corresponding_offer_quantity(self):
        rows, _ = collectors.parse_itembay_items(itembay_response(itembay_item_row(
            iPrice=200000, biWantQuantity=2, tranPrice="100,000", biMinQuantity=1)), OBSERVED_AT)
        self.assertEqual(rows[0]["unitPrice"], 100000)

    def test_unmapped_ambiguous_and_invalid_counts_are_separate_without_original_subject(self):
        self.match.side_effect = [("unmapped", None), ("ambiguous", None), ("invalid", None)]
        rows, counts = collectors.parse_barotem_items(barotem_response(
            barotem_item_row(number="1"), barotem_item_row(number="2"), barotem_item_row(number="3")), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(counts, {"unmapped": 1, "ambiguous": 1, "invalid": 1})
        self.assertNotIn("product_name", str(counts))

    def test_invalid_item_numbers_and_wrong_asset_do_not_enter_samples(self):
        for value in [0, -1, None, True, "NaN", float("inf")]:
            with self.subTest(value=value):
                rows, counts = collectors.parse_itembay_items(itembay_response(
                    itembay_item_row(biWantQuantity=value)), OBSERVED_AT)
                self.assertEqual(rows, [])
                self.assertEqual(counts["invalid"], 1)
        rows, counts = collectors.parse_itembay_items(itembay_response(
            itembay_item_row(biWantQuantity=1.5), itembay_row()), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(counts["invalid"], 2)

    def test_unknown_enchant_and_blessing_preserved_and_ads_deduplicated(self):
        match = {**ITEM_MATCH, "enchant": None, "blessing": "unknown"}
        self.match.return_value = ("mapped", match)
        row = itembay_item_row()
        rows, counts = collectors.parse_itembay_items(itembay_response(
            row, copy.deepcopy(row), adverts=[itembay_item_row(iItemSeq="888888")]), OBSERVED_AT)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["enchant"])
        self.assertEqual(rows[0]["blessing"], "unknown")
        self.assertEqual(counts["invalid"], 0)

    def test_unregistered_canonical_name_rejected(self):
        self.match.return_value = ("mapped", {**ITEM_MATCH, "itemName": "판매자 임의 제목"})
        rows, counts = collectors.parse_itembay_items(itembay_response(itembay_item_row()), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(counts["invalid"], 1)

    def test_public_items_never_publish_raw_subject_or_seller_fields(self):
        rows, _ = collectors.parse_itembay_items(itembay_response(
            itembay_item_row(vcSubject="8화염의검 연락처 010-0000-0000 private-seller")), OBSERVED_AT)
        self.assertEqual(rows[0]["title"], "리니지 클래식 아이템")
        self.assertNotIn("010-0000", str(rows))
        self.assertNotIn("private", str(rows))
        self.assertNotIn("mappingVersion", rows[0])


class ItemCollectionTests(unittest.TestCase):
    def setUp(self):
        self.matcher = patch.object(collectors, "_catalog_match", return_value=("mapped", copy.deepcopy(ITEM_MATCH)))
        self.match = self.matcher.start()
        self.addCleanup(self.matcher.stop)

    def test_max_three_barotem_item_pages_and_unique_eligible_count(self):
        with patch.object(collectors, "_barotem_request", return_value=barotem_response(barotem_item_row())) as request:
            result = collectors.collect_items("barotem", pages=3)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args.args, (3, "2381r870"))
        self.assertEqual(result["rawCount"], 3)
        self.assertEqual(result["eligibleTotal"], 1)
        self.assertEqual(result["pagesFetched"], 3)

    def test_no_mapped_titles_is_successful_empty_sample_with_coverage_counts(self):
        self.match.return_value = ("unmapped", None)
        with patch.object(collectors, "_barotem_request", return_value=barotem_response(barotem_item_row())):
            result = collectors.collect_items("barotem", pages=1)
        self.assertEqual(result["listings"], [])
        self.assertEqual(result["rawCount"], 1)
        self.assertEqual(result["excludedCounts"]["unmapped"], 1)
        self.assertEqual(result["rejectedCount"], 0)
        self.assertEqual(result["pagesFetched"], 1)

    def test_wrong_asset_response_is_source_failure_with_no_further_requests(self):
        with patch.object(collectors, "_itembay_request", return_value=itembay_response(itembay_row())) as request:
            with self.assertRaisesRegex(collectors.CollectorError, "different asset type"):
                collectors.collect_items("itembay", pages=3)
        self.assertEqual(request.call_count, 1)

    def test_max_four_itembay_pages_separate_completed_and_asks(self):
        responses = [itembay_response(itembay_item_row())] * 3 + [itembay_response(
            itembay_item_row(tiSellStatus=3, iTranPrice=180000, biTranQuantity=1))]
        with patch.object(collectors, "_itembay_request", side_effect=responses) as request:
            result = collectors.collect_items("itembay", pages=3)
        self.assertEqual(request.call_count, 4)
        self.assertEqual(request.call_args.args, (1, "completed", "4"))
        self.assertEqual(result["pagesFetched"], 4)
        self.assertEqual(result["rawCount"], 4)
        self.assertEqual(result["eligibleTotal"], 2)
        self.assertEqual(result["totalListings"], 6002)

    def test_items_queries_use_verified_item_category_and_type(self):
        with patch.object(collectors, "_request_json", return_value={}) as request:
            collectors._itembay_request(1, "ask", "4")
        query = parse_qs(urlsplit(request.call_args.args[0]).query)
        self.assertEqual(query["tiItemType"], ["4"])
        self.assertTrue(request.call_args.kwargs["referer"].endswith("/type-4"))


class ItemCatalogIntegrationTests(unittest.TestCase):
    def test_observed_full_name_and_alias_repeat_maps_one_item_at_one_quantity(self):
        rows, counts = collectors.parse_barotem_items(barotem_response(barotem_item_row(
            product_name="8화검 8화염의검 팜")), OBSERVED_AT)
        self.assertEqual(counts, {"unmapped": 0, "ambiguous": 0, "invalid": 0})
        self.assertEqual(rows[0]["itemName"], "화염의 검")
        self.assertEqual(rows[0]["enchant"], 8)

    def test_distinct_items_or_same_item_distinct_enchantments_are_excluded(self):
        for title in ["8화염의검 +7수정장갑 판매", "8화검 9화염의검 팜"]:
            with self.subTest(title=title):
                rows, counts = collectors.parse_barotem_items(barotem_response(
                    barotem_item_row(product_name=title)), OBSERVED_AT)
                self.assertEqual(rows, [])
                self.assertEqual(counts["ambiguous"], 1)

    def test_declared_same_item_quantity_must_agree_with_source_quantity(self):
        rows, counts = collectors.parse_barotem_items(barotem_response(barotem_item_row(
            product_name="8화검 2개 판매", single_unit="1 개")), OBSERVED_AT)
        self.assertEqual(rows, [])
        self.assertEqual(counts["ambiguous"], 1)
        rows, counts = collectors.parse_barotem_items(barotem_response(barotem_item_row(
            product_name="8화검 2개 판매", single_unit="2 개", baro_price="360000")), OBSERVED_AT)
        self.assertEqual(counts["ambiguous"], 0)
        self.assertEqual(rows[0]["unitPrice"], 180000)


if __name__ == "__main__":
    unittest.main()

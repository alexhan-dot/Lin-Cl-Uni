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


if __name__ == "__main__":
    unittest.main()

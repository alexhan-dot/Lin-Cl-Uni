"""Bounded, anonymous sampling of public Lineage Classic currency listings.

These are internal website listing endpoints, not supported partner APIs. Only
the first three normal-list pages are sampled; paid advertisement arrays and all
seller, contact, comment, and original subject fields are deliberately discarded.
Prices describe source-listed offers or source-marked completed transactions,
not a verified market-wide execution feed.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15
MAX_ASK_PAGES = 3
ADENA_REFERENCE_QUANTITY = 1_000_000
BAROTEM_CATEGORY = "2382r902"
ITEMBAY_GAME = "3828"
_PUBLIC_ID = re.compile(r"[0-9]{1,32}\Z")
_NUMERIC = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z")
_KOREAN_TOKEN = re.compile(r"([0-9]+(?:\.[0-9]+)?)(억|만|천|백|십)?")
_MULTIPLIERS = {"": 1, "십": 10, "백": 100, "천": 1000,
                "만": 10_000, "십만": 100_000, "백만": 1_000_000,
                "천만": 10_000_000, "억": 100_000_000}
_SAMPLE_WARNING = "일부 일반 매물 페이지를 수집한 표본이며 전체 시장 시세가 아닙니다."


class CollectorError(RuntimeError):
    """A source failed to return a usable public listing response."""


class _SameSiteHTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urlsplit(request.full_url), urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname:
            raise CollectorError("Unexpected source redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _positive_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Invalid numeric value")
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not _NUMERIC.fullmatch(value):
            raise ValueError("Invalid numeric string")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Value must be positive and finite")
    return result


def _nonnegative_number(value):
    if value == "0" or (not isinstance(value, bool) and value == 0):
        return 0.0
    return _positive_number(value)


def _adena_quantity(value):
    """Parse the source's explicit Korean currency quantity, never a title."""
    if not isinstance(value, str):
        raise ValueError("Missing currency quantity")
    text = re.sub(r"\s+", "", value).replace(",", "")
    if not text.endswith("아데나"):
        raise ValueError("Unexpected currency")
    text = text[:-3]
    if text in _MULTIPLIERS:
        return float(_MULTIPLIERS[text])
    position, quantity = 0, 0.0
    for match in _KOREAN_TOKEN.finditer(text):
        if match.start() != position:
            raise ValueError("Unknown currency quantity format")
        quantity += float(match.group(1)) * _MULTIPLIERS[match.group(2) or ""]
        position = match.end()
    if position != len(text) or not text:
        raise ValueError("Unknown currency quantity format")
    return _positive_number(quantity)


def _listing(public_id, source, server, kind, price, quantity, observed_at):
    public_id = str(public_id)
    if not _PUBLIC_ID.fullmatch(public_id):
        raise ValueError("Invalid listing identifier")
    if not isinstance(server, str) or not server.strip() or len(server) > 40:
        raise ValueError("Invalid server name")
    server = server.strip()
    if any(char in server for char in "<>\r\n\t"):
        raise ValueError("Invalid server name")
    price, quantity = _positive_number(price), _positive_number(quantity)
    unit_price = price / quantity * ADENA_REFERENCE_QUANTITY
    if not math.isfinite(unit_price) or unit_price <= 0:
        raise ValueError("Invalid normalized price")
    if source == "barotem":
        url = "https://www.barotem.com/product/view/" + public_id
    else:
        url = "https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=" + public_id
    return {
        "id": source + ":" + public_id,
        "source": source,
        "server": server,
        "kind": kind,
        "unitPrice": round(unit_price, 6),
        "priceKRW": price,
        "quantity": quantity,
        "observedAt": observed_at,
        "url": url,
        "title": "리니지 클래식 아데나",
    }


def _barotem_row(row, observed_at):
    if row.get("category") != BAROTEM_CATEGORY or row.get("sell_type") != "sell":
        raise ValueError("Unexpected game or listing type")
    price = _positive_number(row.get("baro_price"))
    if str(row.get("saletype")) == "1":
        # Bundles: baro_price is the total price. unit_price is rounded text.
        quantity = _adena_quantity(row.get("single_unit"))
    elif str(row.get("saletype")) == "0":
        # Split offers: baro_price is per saleUnitText, not the displayed minimum.
        multiplier = _adena_quantity(row.get("saleUnitText"))
        minimum = _positive_number(row.get("min_cnt"))
        available_units = _nonnegative_number(row.get("work_same_cnt"))
        if available_units < minimum:
            # The site's renderer switches to an explicit remaining-stock bundle.
            quantity = _adena_quantity(row.get("deal_quantity"))
            deal_price = row.get("deal_price")
            if not isinstance(deal_price, str) or not deal_price.endswith("원"):
                raise ValueError("Invalid remaining bundle price")
            price = _positive_number(deal_price[:-1])
        else:
            quantity = minimum * multiplier
            price *= minimum
    else:
        raise ValueError("Unsupported sale type")
    return _listing(row.get("number"), "barotem", row.get("server"),
                    "ask", price, quantity, observed_at)


def _itembay_row(row, observed_at, kind):
    # The live listing DTO currently emits iGameSeq=0, even on a game-specific
    # query. The request itself pins the game; still reject an explicit other ID.
    if str(row.get("iGameSeq")) not in ("0", ITEMBAY_GAME) or str(row.get("tiItemType")) != "3":
        raise ValueError("Unexpected game or listing type")
    status = str(row.get("tiSellStatus"))
    if kind == "completed":
        if status != "3":
            raise ValueError("Not a completed listing")
        # A division listing can execute a quantity different from its offer.
        # Do not substitute iPrice or biWantQuantity when trade fields are absent.
        price = _positive_number(row.get("iTranPrice"))
        quantity = _positive_number(row.get("biTranQuantity"))
    else:
        if status != "0":
            raise ValueError("Not a current available listing")
        # The base quote iPrice corresponds to biWantQuantity. tranPrice is the
        # minimum purchase total, so pairing it with biWantQuantity is incorrect.
        price = _positive_number(row.get("iPrice"))
        quantity = _positive_number(row.get("biWantQuantity"))
    return _listing(row.get("iItemSeq"), "itembay", row.get("vcServerName"),
                    kind, price, quantity, observed_at)


def parse_barotem(payload, observed_at):
    """Return normalized safe rows and rejection count from one listing page."""
    if not isinstance(payload, dict) or str(payload.get("code")) != "200":
        raise CollectorError("Barotem listing response rejected")
    if not isinstance(payload.get("rows"), list):
        raise CollectorError("Barotem listing schema changed")
    return _parse_rows(payload["rows"], _barotem_row, observed_at)


def parse_itembay(payload, observed_at, kind="ask"):
    """Only normal list rows are sampled; powerZonelist advertising is excluded."""
    if kind not in ("ask", "completed"):
        raise ValueError("Unknown listing kind")
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise CollectorError("ItemBay listing response rejected")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise CollectorError("ItemBay listing schema changed")
    return _parse_rows(data["list"], lambda row, at: _itembay_row(row, at, kind), observed_at)


def _parse_rows(rows, parser, observed_at):
    normalized, rejected, seen = [], 0, set()
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("Invalid listing row")
            listing = parser(row, observed_at)
        except (ValueError, TypeError, OverflowError):
            rejected += 1
            continue
        identity = (listing["id"], listing["kind"])
        if identity not in seen:
            normalized.append(listing)
            seen.add(identity)
    return normalized, rejected


def _request_json(url, *, body=None, referer):
    request = Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AdenaPriceSampler/0.1)",
        "Accept": "application/json",
        "Referer": referer,
        # Matches the site's jQuery public-list request. Barotem rejects otherwise
        # with code=100 despite a valid POST body and HTTP 200 response.
        "X-Requested-With": "XMLHttpRequest",
        **({"Content-Type": "application/x-www-form-urlencoded"} if body is not None else {}),
    })
    try:
        # HTTPSHandler uses Python's default verified TLS trust configuration.
        with build_opener(_SameSiteHTTPSRedirects()).open(
                request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise CollectorError("Source response exceeded size limit")
            result = json.loads(data.decode("utf-8-sig"))
    except HTTPError as exc:
        raise CollectorError("Source HTTP " + str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise CollectorError("Source connection failed") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CollectorError("Source returned invalid JSON") from None
    return result


def _barotem_request(page):
    fields = {"page": page, "sell": "sell", "category": "", "display": "1",
              "orderby": "1", "minpay": "", "maxpay": "", "search_word": "",
              "brand": "", "buyloc": "", "total": "no"}
    fields.update({"opt" + str(number): "" for number in range(1, 11)})
    return _request_json(
        "https://www.barotem.com/product/productTable/" + BAROTEM_CATEGORY,
        body=urlencode(fields).encode("ascii"),
        referer="https://www.barotem.com/product/lists/" + BAROTEM_CATEGORY)


def _itembay_request(page, kind):
    fields = {
        "iGameSeq": ITEMBAY_GAME, "tiItemType": "3", "iPageNo": page,
        "iLimit": "48", "vcOrderBy": "OrderByItem", "bPriceOrder": "0",
        "chkTranPossible": "true" if kind == "ask" else "false",
        "chkTranComplete": "true" if kind == "completed" else "false",
        "chkReward": "false", "iMinPrice": "", "iMaxPrice": "",
        "biMinQuantity": "", "biMaxQuantity": "", "arrServerSeq": "",
        "arrServerKey": "", "arrDetailList": "", "vcSearchTxt1": "",
        "tiPaging": "1", "bPremiumList": "0", "tiCreditLevelNormal": "0",
        "tiCreditLevelBronze": "1", "tiCreditLevelSilver": "3",
        "tiCreditLevelGold": "5", "tiCreditLevelVip": "6", "chkExcellent": "false",
        "chkDuplication": "false", "chkDirectMessage": "false", "vcSearchTxt2": "",
        "iMinLevel": "", "iMaxLevel": "", "isRenewal": "true",
    }
    return _request_json(
        "https://www.itembay.com/item/api/sell/getSearchItemSellList?" + urlencode(fields),
        referer="https://www.itembay.com/item/sell/game-3828/type-3")


def _total_count(value):
    try:
        number = _nonnegative_number(value)
        return int(number) if number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def collect_source(source_id, pages=3):
    """Sample <=3 ask pages and, for ItemBay, one completed page, without retries.

    A failed first ask page raises CollectorError. Later page errors preserve
    usable earlier samples with a warning. totalListings refers to ask listings
    only, when the source supplies a total; it never implies complete coverage.
    """
    if source_id not in ("barotem", "itembay"):
        raise ValueError("Unsupported source")
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= MAX_ASK_PAGES:
        raise ValueError("pages must be between 1 and 3")
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = {"listings": [], "totalListings": None, "pagesFetched": 0,
              "rejectedCount": 0, "warnings": [_SAMPLE_WARNING]}
    seen = set()

    def append(rows, rejected):
        result["rejectedCount"] += rejected
        for row in rows:
            identity = (row["id"], row["kind"])
            if identity not in seen:
                result["listings"].append(row)
                seen.add(identity)

    for page in range(1, pages + 1):
        try:
            if source_id == "barotem":
                payload = _barotem_request(page)
                rows, rejected = parse_barotem(payload, observed_at)
                count = _total_count(payload.get("total"))
                raw_rows = payload["rows"]
            else:
                payload = _itembay_request(page, "ask")
                rows, rejected = parse_itembay(payload, observed_at)
                count = _total_count(payload["data"].get("iTotalCount"))
                raw_rows = payload["data"]["list"]
            if raw_rows and not rows:
                raise CollectorError("All source listing rows were rejected")
        except CollectorError:
            if page == 1:
                raise
            result["warnings"].append("추가 판매 매물 페이지 조회가 실패해 앞선 페이지 표본만 유지합니다.")
            break
        if count is not None:
            result["totalListings"] = count
        result["pagesFetched"] += 1
        append(rows, rejected)
        if not raw_rows:
            break

    if source_id == "itembay":
        result["warnings"].append("완료 거래는 1페이지 표본이며 정확한 체결 시각은 확인되지 않았습니다.")
        try:
            payload = _itembay_request(1, "completed")
            rows, rejected = parse_itembay(payload, observed_at, "completed")
            if payload["data"]["list"] and not rows:
                raise CollectorError("All source completed listing rows were rejected")
            result["pagesFetched"] += 1
            append(rows, rejected)
        except CollectorError:
            result["warnings"].append("완료 매물 조회가 실패해 판매 호가 표본만 유지합니다.")
    return result

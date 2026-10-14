"""Collect a bounded market sample for Pages, retaining the last good publish."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market.server import PriceService
from market.store import Store


MAX_PREVIOUS_BYTES = 1_048_576
PREVIOUS_TIMEOUT_SECONDS = 10
LOGGER = logging.getLogger("market.static")


class PreviousSnapshotError(RuntimeError):
    """An old public snapshot was unavailable or did not pass validation."""


def _validate_url(url):
    if not isinstance(url, str) or len(url) > 1024:
        raise PreviousSnapshotError("Invalid published snapshot URL")
    parsed = urlsplit(url)
    try:
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".github.io")
            or parsed.username or parsed.password or not valid_port or parsed.query or parsed.fragment
            or not parsed.path.endswith("/prices.json")):
        raise PreviousSnapshotError("Expected this Pages site's HTTPS snapshot URL")
    return parsed


class _SameSiteHTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old = _validate_url(request.full_url)
        new = _validate_url(newurl)
        if old.hostname != new.hostname:
            raise PreviousSnapshotError("Unexpected published snapshot redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _read_response(response):
    content_length = getattr(response, "headers", {}).get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_PREVIOUS_BYTES:
                raise PreviousSnapshotError("Previous snapshot is too large")
        except ValueError as error:
            raise PreviousSnapshotError("Invalid snapshot length") from error
    raw = response.read(MAX_PREVIOUS_BYTES + 1)
    if len(raw) > MAX_PREVIOUS_BYTES:
        raise PreviousSnapshotError("Previous snapshot is too large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise PreviousSnapshotError("Previous snapshot is not JSON") from error
    if not isinstance(payload, dict) or type(payload.get("schemaVersion")) is not int or payload.get("schemaVersion") != 1:
        raise PreviousSnapshotError("Unsupported previous snapshot")
    return payload


def fetch_previous(url):
    _validate_url(url)
    request = Request(url, headers={"User-Agent": "Lin-Cl-Uni-Market/1.0", "Accept": "application/json"})
    try:
        with build_opener(_SameSiteHTTPSRedirects()).open(request, timeout=PREVIOUS_TIMEOUT_SECONDS) as response:
            return _read_response(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise PreviousSnapshotError("Published snapshot could not be read") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PreviousSnapshotError("Published snapshot could not be reached") from error


def refresh(previous_url, data_dir, output, *, collector=None, fetcher=fetch_previous, now=None, pages=3):
    store = Store(data_dir, interval_seconds=600, pages_per_source=pages)
    if previous_url:
        try:
            previous = fetcher(previous_url)
            if previous is not None:
                store.seed_snapshot(previous)
        except (PreviousSnapshotError, ValueError, TypeError) as error:
            LOGGER.warning("Previous snapshot unavailable (%s); trying a fresh collection", type(error).__name__)
    service = PriceService(store, collector=collector, interval=600, pages=pages,
                           utcnow=(lambda: now) if now is not None else (lambda: datetime.now(timezone.utc)))
    payload = service.run_cycle()
    if not payload["listings"]:
        raise RuntimeError("No usable retained or newly collected prices; refusing an empty publication")
    service.export(output)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-url", help="The site's existing https://OWNER.github.io/.../test/data/prices.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".market-data")
    parser.add_argument("--output", type=Path, default=ROOT / ".market-data" / "prices.json")
    parser.add_argument("--pages", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        payload = refresh(args.previous_url, args.data_dir, args.output, pages=args.pages)
    except (ValueError, RuntimeError, OSError) as error:
        LOGGER.error("Static snapshot refresh failed (%s)", type(error).__name__)
        return 1
    LOGGER.info("Ready to publish %s sampled listings; source statuses: %s", len(payload["listings"]),
                ", ".join(source["id"] + "=" + source["status"] for source in payload["sources"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

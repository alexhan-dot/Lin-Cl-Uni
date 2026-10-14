"""A cached server with currency collection and an independent item deadline."""

from __future__ import annotations

import argparse
import copy
import hashlib
import logging
import mimetypes
import os
import tempfile
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .store import ACTIVE_SOURCES, Store, encode_json, parse_timestamp, timestamp, utcnow


LOGGER = logging.getLogger("market")
STATIC_FILES = {"market.html", "market.css", "market.js", "index.html", "admin.html",
                "styles.css", "admin.css", "script.js", "admin.js", "site-data.js"}
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gif"}


class PriceService:
    def __init__(self, store, collector=None, interval=600, pages=3, utcnow=utcnow,
                 monotonic=time.monotonic, item_collector=None, item_interval=3600):
        self.store = store
        self.interval = int(interval)
        self.item_interval = int(item_interval)
        self.pages = int(pages)
        self.utcnow = utcnow
        self.monotonic = monotonic
        if self.interval <= 0 or self.item_interval <= 0 or not 1 <= self.pages <= 3:
            raise ValueError("Invalid collection schedule")
        self.collector = collector
        self.item_collector = item_collector
        # Injecting only a currency collector keeps older offline callers and
        # tests isolated. The normal CLI enables both real collectors lazily.
        self._items_enabled = item_collector is not None or collector is None
        self._cache_lock = threading.Lock()
        self._cycle_lock = threading.Lock()
        self._collecting = False
        self._cycles = 0
        self._successful_cycles = 0
        self._stop_event = threading.Event()
        self._scheduler = None
        payload = self.store.load_snapshot() or self.store.empty_snapshot(now=self.utcnow())
        payload = copy.deepcopy(payload)
        if self._items_enabled and "items" not in payload:
            payload["items"] = self.store.empty_item_snapshot(now=self.utcnow())
        last_success = payload.get("lastSuccessfulUpdateAt")
        if last_success and (self.utcnow() - parse_timestamp(last_success)).total_seconds() > self.interval * 2:
            payload["stale"] = True
            for source in payload["sources"]:
                if source.get("updatedAt") and (self.utcnow() - parse_timestamp(source["updatedAt"])).total_seconds() > self.interval * 2:
                    source["stale"] = True
        items = payload.get("items")
        if items:
            last_item_success = items.get("lastSuccessfulUpdateAt")
            if last_item_success and (self.utcnow() - parse_timestamp(last_item_success)).total_seconds() > self.item_interval * 2:
                items["stale"] = True
                for source in items.get("sources", []):
                    if source.get("updatedAt") and (self.utcnow() - parse_timestamp(source["updatedAt"])).total_seconds() > self.item_interval * 2:
                        source["stale"] = True
        self._publish(payload)

    def _publish(self, payload):
        body = encode_json(payload)
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        with self._cache_lock:
            self._payload = payload
            self._body = body
            self._etag = etag

    def cached_response(self):
        with self._cache_lock:
            return self._body, self._etag

    def health(self):
        with self._cache_lock:
            payload = self._payload
            last_success = payload.get("lastSuccessfulUpdateAt")
            stale = payload["stale"] or not last_success or (self.utcnow() - parse_timestamp(last_success)).total_seconds() > self.interval * 2
            items = payload.get("items") or {}
            last_item_success = items.get("lastSuccessfulUpdateAt")
            items_stale = bool(items.get("stale", True) or not last_item_success
                               or (self.utcnow() - parse_timestamp(last_item_success)).total_seconds() > self.item_interval * 2)
            item_health = {"enabled": self._items_enabled, "intervalSeconds": self.item_interval,
                           "status": "ok" if last_item_success and not items_stale else "degraded" if self._items_enabled or items else "disabled",
                           "generatedAt": items.get("generatedAt"),
                           "lastSuccessfulUpdateAt": last_item_success,
                           "nextUpdateAt": items.get("nextUpdateAt"), "stale": items_stale,
                           "sources": [{key: source.get(key) for key in ("id", "status", "updatedAt", "sampleCount", "completedCount", "error")}
                                       for source in items.get("sources", [])]}
            ready = last_success and not stale and (not self._items_enabled or not items_stale)
            return {"status": "ok" if ready else "degraded", "collecting": self._collecting,
                    "intervalSeconds": self.interval, "cycles": self._cycles, "successfulCycles": self._successful_cycles,
                    "generatedAt": payload["generatedAt"], "lastSuccessfulUpdateAt": last_success,
                    "nextUpdateAt": payload["nextUpdateAt"], "stale": stale,
                    "sources": [{key: source[key] for key in ("id", "status", "updatedAt", "sampleCount", "completedCount", "error")} for source in payload["sources"]],
                    "items": item_health}

    def run_cycle(self, scheduled_start=None):
        with self._cycle_lock:
            scheduled_start = self.monotonic() if scheduled_start is None else scheduled_start
            cycle_start = self.utcnow()
            collect_items_now = self._items_enabled and self.store.items_due(cycle_start)
            with self._cache_lock:
                self._collecting = True
            try:
                if self.collector is None:
                    from .collectors import collect_source
                    collector = collect_source
                else:
                    collector = self.collector
                results = {}
                for source in ACTIVE_SOURCES:
                    try:
                        results[source["id"]] = collector(source["id"], pages=self.pages)
                    except Exception as error:
                        results[source["id"]] = error
                        LOGGER.warning("%s collection failed (%s)", source["id"], type(error).__name__)
                item_results = None
                if collect_items_now:
                    if self.item_collector is None:
                        from .collectors import collect_items
                        item_collector = collect_items
                    else:
                        item_collector = self.item_collector
                    item_results = {}
                    for source in ACTIVE_SOURCES:
                        try:
                            item_results[source["id"]] = item_collector(source["id"], pages=self.pages)
                        except Exception as error:
                            item_results[source["id"]] = error
                            LOGGER.warning("%s item collection failed (%s)", source["id"], type(error).__name__)
                current = self.monotonic()
                next_tick = scheduled_start + self.interval
                while next_tick <= current:
                    next_tick += self.interval
                now = self.utcnow()
                next_update_at = now + timedelta(seconds=max(0, next_tick - current))
                payload = self.store.apply_cycle(results, now=now, next_update_at=next_update_at)
                if item_results is not None:
                    self.store.apply_item_cycle(item_results, now=now,
                                                next_update_at=cycle_start + timedelta(seconds=self.item_interval))
                    payload = self.store.load_snapshot()
                self._publish(payload)
                with self._cache_lock:
                    self._cycles += 1
                    if any(source["status"] == "ok" for source in payload["sources"]):
                        self._successful_cycles += 1
                self.export(self.store.data_dir / "prices.json")
                LOGGER.info("Cycle %s published: %s listings", self._cycles, len(payload["listings"]))
                return payload
            finally:
                with self._cache_lock:
                    self._collecting = False

    def scheduler_loop(self, stop_event):
        next_tick = self.monotonic()
        while not stop_event.is_set():
            try:
                self.run_cycle(scheduled_start=next_tick)
            except Exception as error:
                LOGGER.error("Snapshot publication failed (%s)", type(error).__name__)
            next_tick += self.interval
            current = self.monotonic()
            while next_tick <= current:
                next_tick += self.interval
            if stop_event.wait(max(0, next_tick - current)):
                break

    def start(self):
        if self._scheduler and self._scheduler.is_alive():
            return
        self._stop_event.clear()
        self._scheduler = threading.Thread(target=self.scheduler_loop, args=(self._stop_event,), name="price-collector", daemon=True)
        self._scheduler.start()

    def stop(self):
        self._stop_event.set()

    def export(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body, _ = self.cached_response()
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as output:
            output.write(body)
            temporary = Path(output.name)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def create_server(service, host="127.0.0.1", port=0, static_root=None):
    root = Path(static_root or Path(__file__).resolve().parents[1]).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MarketHTTP/1.0"

        def setup(self):
            self.request.settimeout(10)
            super().setup()

        def _respond(self, status, body=b"", content_type="text/plain; charset=utf-8", cache="no-store", etag=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if status != 304:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            if self.command != "HEAD" and status != 304:
                self.wfile.write(body)

        def _serve(self):
            if len(self.path) > 2048:
                return self._respond(414, b"URI too long")
            path = unquote(urlsplit(self.path).path)
            if "\x00" in path or "\\" in path or any(part in (".", "..") for part in path.split("/")):
                return self._respond(404, b"Not found")
            if path == "/api/prices":
                body, etag = service.cached_response()
                matches = [value.strip().removeprefix("W/") for value in self.headers.get("If-None-Match", "").split(",")]
                if etag in matches or "*" in matches:
                    return self._respond(304, content_type="application/json; charset=utf-8", cache="public, max-age=30", etag=etag)
                return self._respond(200, body, "application/json; charset=utf-8", "public, max-age=30", etag)
            if path == "/api/health":
                return self._respond(200, encode_json(service.health()), "application/json; charset=utf-8")
            relative = "market.html" if path == "/" else "index.html" if path == "/academy.html" else path.lstrip("/")
            allowed = relative in STATIC_FILES or (relative.startswith("assets/") and len(relative.split("/")) == 2 and Path(relative).suffix.lower() in ASSET_SUFFIXES)
            if not allowed:
                return self._respond(404, b"Not found")
            candidate = (root / relative).resolve()
            if candidate != root / relative or not candidate.is_relative_to(root) or not candidate.is_file():
                return self._respond(404, b"Not found")
            size = candidate.stat().st_size
            if size > 16 * 1024 * 1024:
                return self._respond(404, b"Not found")
            body = candidate.read_bytes()
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                content_type += "; charset=utf-8"
            matches = [value.strip().removeprefix("W/") for value in self.headers.get("If-None-Match", "").split(",")]
            if etag in matches or "*" in matches:
                return self._respond(304, content_type=content_type, cache="public, max-age=300", etag=etag)
            return self._respond(200, body, content_type, "public, max-age=300", etag)

        def do_GET(self):
            self._serve()

        def do_HEAD(self):
            self._serve()

        def _method_not_allowed(self):
            self.close_connection = True
            self._respond(405, b"Method not allowed")

        do_POST = _method_not_allowed
        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed

        def log_message(self, format, *args):
            # Log route status without attacker-supplied query strings.
            LOGGER.debug("HTTP %s", self.command)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve cached Lineage Classic currency and item samples")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--item-interval", type=int, default=3600)
    parser.add_argument("--pages", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / ".market-data"))
    parser.add_argument("--no-collect", action="store_true", help="Serve retained snapshots without any upstream requests")
    parser.add_argument("--once", action="store_true", help="Collect and export one snapshot, then exit")
    parser.add_argument("--export-file", help="Additional JSON export location")
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.item_interval <= 0:
        parser.error("--interval and --item-interval must be positive")
    if args.once and args.no_collect:
        parser.error("--once and --no-collect cannot be combined")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(args.data_dir, interval_seconds=args.interval, pages_per_source=args.pages,
                  item_interval_seconds=args.item_interval)
    service = PriceService(store, interval=args.interval, pages=args.pages, item_interval=args.item_interval)
    if args.once:
        payload = service.run_cycle()
        if args.export_file:
            service.export(args.export_file)
        return 0 if any(source["status"] == "ok" for source in payload["sources"]) else 1
    if args.export_file:
        service.export(args.export_file)
    server = create_server(service, args.host, args.port)
    if not args.no_collect:
        service.start()
    LOGGER.info("Serving on port %s; currency interval %ss; item interval %ss; sampling %s ask pages per source",
                args.port, args.interval, args.item_interval, args.pages)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

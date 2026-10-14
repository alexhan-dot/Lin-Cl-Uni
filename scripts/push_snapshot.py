"""Upload a normalized snapshot using credentials injected into this process."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

def upload(path: Path) -> None:
    endpoint = os.environ.get("MARKET_UPLOAD_URL", "")
    token = os.environ.get("MARKET_UPLOAD_TOKEN", "")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("MARKET_UPLOAD_URL must be an HTTPS upload endpoint")
    if not token:
        raise ValueError("MARKET_UPLOAD_TOKEN is not configured")
    payload = path.read_bytes()
    data = json.loads(payload)
    if len(payload) > 1_000_000 or data.get("schemaVersion") != 1 or not data.get("listings"):
        raise ValueError("A valid collected snapshot smaller than 1MB is required")
    request = urllib.request.Request(endpoint, payload, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token,
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or not json.load(response).get("ok"):
                raise RuntimeError("Snapshot upload was not acknowledged")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Snapshot upload failed with HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("Snapshot upload network failure") from None
    print(f"Uploaded {len(data['listings'])} normalized listings")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path(".market-data/prices.json"))
    args = parser.parse_args()
    try:
        upload(args.file)
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

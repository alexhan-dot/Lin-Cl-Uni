"""Package the market UI and an actual collected snapshot for static hosting."""
import argparse
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

def build(snapshot: Path, destination: Path, preserve_landing=False, scheduled=False) -> None:
    if preserve_landing:
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "admin.html", "styles.css", "script.js", "site-data.js", "admin.css", "admin.js"):
            shutil.copy2(ROOT / name, destination / name)
        shutil.copytree(ROOT / "assets", destination / "assets", dirs_exist_ok=True)
        (destination / ".nojekyll").touch()
        build(snapshot, destination / "test", scheduled=scheduled)
        return
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or not payload.get("listings"):
        raise ValueError("A real collected snapshot with listings is required")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("market.css", "market.js", "styles.css", "script.js", "site-data.js", "admin.css"):
        shutil.copy2(ROOT / name, destination / name)
    market_html = (ROOT / "market.html").read_text(encoding="utf-8")
    if scheduled:
        market_html = market_html.replace("</head>", '<meta name="market-static-updates" content="scheduled">\n</head>')
    (destination / "index.html").write_text(market_html, encoding="utf-8")
    shutil.copy2(ROOT / "index.html", destination / "academy.html")
    admin = (ROOT / "admin.html").read_text(encoding="utf-8").replace('href="index.html"', 'href="academy.html"')
    (destination / "admin.html").write_text(admin, encoding="utf-8")
    admin_js = (ROOT / "admin.js").read_text(encoding="utf-8").replace('window.open("index.html"', 'window.open("academy.html"')
    (destination / "admin.js").write_text(admin_js, encoding="utf-8")
    shutil.copytree(ROOT / "assets", destination / "assets", dirs_exist_ok=True)
    (destination / "data").mkdir(exist_ok=True)
    (destination / "data" / "prices.json").write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (destination / ".nojekyll").touch()
    print(f"Packaged {len(payload['listings'])} observed listings into {destination}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / ".market-data" / "prices.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--preserve-landing", action="store_true", help="Keep the existing landing at root and place the pilot under /test/")
    parser.add_argument("--scheduled", action="store_true", help="Label static hosting as scheduled updates rather than a one-off preview")
    args = parser.parse_args()
    build(args.snapshot, args.output, args.preserve_landing, args.scheduled or os.environ.get("AUTOMATIC_MARKET_UPDATES") == "true")

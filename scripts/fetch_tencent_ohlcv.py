#!/usr/bin/env python3
"""Fetch reproducible A-share daily OHLCV snapshots from Tencent's public K-line endpoint.

This is a fallback for report snapshots when the authenticated WeStock CLI is
unavailable. It intentionally requests unadjusted daily bars; corporate-action
gaps must be considered before using the output for long-horizon backtests.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"


def fetch(code, start, end, bars):
    query = urlencode({"param": f"{code},day,{start},{end},{bars}"})
    request = Request(
        f"{ENDPOINT}?{query}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise ValueError(f"{code}: {payload.get('msg') or 'bad response'}")
    series = payload.get("data", {}).get(code, {}).get("day")
    if not series:
        raise ValueError(f"{code}: no daily bars returned")
    rows = []
    for item in series:
        if len(item) < 6:
            continue
        rows.append({
            "timestamp": item[0],
            "open": float(item[1]),
            "close": float(item[2]),
            "high": float(item[3]),
            "low": float(item[4]),
            "volume": float(item[5]),
        })
    return rows


def write_csv(path, rows, as_of):
    filtered = []
    for row in rows:
        if as_of and row["timestamp"] > as_of:
            continue
        if not (row["high"] >= row["low"] > 0 and row["volume"] >= 0):
            raise ValueError(f"Invalid OHLCV for {path.name} on {row['timestamp']}")
        filtered.append(row)
    filtered.sort(key=lambda row: row["timestamp"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(filtered)
    content = path.read_bytes()
    return filtered, hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", required=True, help="Comma-separated prefixed codes")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--as-of", help="Last allowed trading date, YYYY-MM-DD")
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "Tencent public ifzq daily K-line endpoint (unadjusted)",
        "endpoint": ENDPOINT,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": args.start,
        "requested_end": args.end,
        "as_of": args.as_of,
        "adjustment": "none",
        "caveat": "Unadjusted prices may contain ex-dividend or split gaps.",
        "symbols": {},
    }
    for index, code in enumerate(args.codes.split(",")):
        code = code.strip()
        rows = fetch(code, args.start, args.end, args.bars)
        path = output_dir / f"{code}.csv"
        rows, digest = write_csv(path, rows, args.as_of)
        if len(rows) < 60:
            raise ValueError(f"{code}: fewer than 60 bars after as-of filter")
        manifest["symbols"][code] = {
            "file": str(path.name),
            "rows": len(rows),
            "first": rows[0]["timestamp"],
            "last": rows[-1]["timestamp"],
            "last_close": rows[-1]["close"],
            "sha256": digest,
        }
        print(f"{code}: {len(rows)} bars through {rows[-1]['timestamp']} -> {path}")
        if index < len(args.codes.split(",")) - 1:
            time.sleep(0.15)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()

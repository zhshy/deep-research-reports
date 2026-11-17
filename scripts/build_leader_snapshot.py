#!/usr/bin/env python3
"""Build a report-ready leader-stock tactical snapshot by calling the local signal skill."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--leaders", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--source", default="Tencent public ifzq daily K-line, unadjusted")
    parser.add_argument(
        "--source-report",
        default="reports/2026-11-16/核心结论摘要-2026-11-16-收盘.md",
    )
    args = parser.parse_args()

    engine = Path(args.engine_dir).expanduser() / "scripts" / "divergence_signals.py"
    data_dir = Path(args.data_dir).expanduser()
    manifest = json.loads(Path(args.leaders).read_text(encoding="utf-8"))
    if isinstance(manifest, dict):
        leaders = manifest["leaders"]
        source_report = manifest.get("source_report", args.source_report)
    else:
        leaders = manifest
        source_report = args.source_report
    records = []
    for leader in leaders:
        code = leader["code"]
        name = leader["name"]
        category = leader["category"]
        watch = leader["watch"]
        csv_path = data_dir / f"{code}.csv"
        command = [
            "python3", str(engine), str(csv_path),
            "--market", "cn_a_stock",
            "--symbol", code,
            "--timeframe", "day",
            "--bar-status", "closed",
            "--data-source", args.source,
            "--no-strategic-authorization",
            "--tick-size", "0.01",
            "--format", "json",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        result = json.loads(completed.stdout)
        setup = result.get("selected_setup") or {}
        if setup.get("state") == "TRIGGERED":
            technical_state = "TRIGGERED_" + setup["direction"].upper()
        elif setup.get("state") == "WAITING":
            technical_state = "WAIT_TRIGGER_" + setup["direction"].upper()
        elif setup.get("state") == "ALREADY_TRIGGERED_DO_NOT_CHASE":
            technical_state = "EXPIRED_DO_NOT_CHASE"
        else:
            technical_state = "NO_SETUP"
        records.append({
            "code": code,
            "name": name,
            "report_category": category,
            "sector": leader.get("sector"),
            "strategic_watch": watch,
            "as_of": result["as_of"],
            "last_close": result["last_close"],
            "technical_state": technical_state,
            "report_action": result["action"],
            "market_profile": result["market_profile"],
            "setup_type": setup.get("type"),
            "setup_state": setup.get("state"),
            "entry_trigger": setup.get("entry_trigger"),
            "initial_stop": setup.get("initial_stop"),
            "targets": setup.get("targets"),
            "key_levels": result["key_levels"],
            "technical_context": result["technical_context"],
            "location": result["location"],
            "position_scope": result.get("position_scope"),
            "strategic_authorization": result["strategic_authorization"],
            "strategy_version": result["strategy_version"],
            "input_sha256": result["data"]["input_sha256"],
            "warnings": result["warnings"],
        })
        print(f"{code} {name}: {technical_state} / {result['action']}")

    output = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": args.as_of,
        "source_report": source_report,
        "leaders_source": str(Path(args.leaders)),
        "leaders_sha256": hashlib.sha256(Path(args.leaders).read_bytes()).hexdigest(),
        "source_data": args.source + "; unadjusted prices may contain corporate-action gaps",
        "authorization": {
            "status": "NOT_AUTHORIZED",
            "reason": "The source report classifies leaders and states what to wait for, but does not authorize per-stock tactical tranches or entry price bands.",
        },
        "state_summary": dict(Counter(record["technical_state"] for record in records)),
        "leaders": records,
        "limitations": [
            "Technical state does not create strategic authorization.",
            "A-share stocks are T+1 and cannot be shorted without securities lending.",
            "No higher-timeframe CSV was supplied; targets use the current-timeframe fallback.",
            "A no-setup result is not a forecast that price will not move.",
        ],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Snapshot: {output_path}")


if __name__ == "__main__":
    main()

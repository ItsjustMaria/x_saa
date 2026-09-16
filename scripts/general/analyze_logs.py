#!/usr/bin/env python3
"""
Analyze a python-logging generated log file:
  1) Writes errors.csv with detailed info on every ERROR line that contains
     an asset link failure.
  2) Prints an overview of total errors grouped by normalized message type.

Usage: python log_analyzer.py path/to/your.log
"""

import csv
import os
import json
import re
import sys
from collections import Counter
from pathlib import Path
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
#sys.path.append(str(HOME_REPO))
print(HOME_REPO)
project_name = 'analyze_logs'
log_path_name = 'aip_downloads'
log_path = f'data/{log_path_name}/logs/'
path_exists = os.makedirs(Path(HOME_REPO, 'data', project_name, log_path_name, 'output' ), exist_ok=True)
output_path = Path(HOME_REPO, 'data', project_name, log_path_name, 'output')

# One log line: "<timestamp> [LEVEL] <rest>"
LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)"
    r"\s+\[(?P<level>[A-Z]+)\]\s+"
    r"(?P<message>.*)$"
)

# The specific link-error lines: "Error linking asset_id=X to record_id=Y: {json}"
LINK_ERROR_RE = re.compile(
    r"Error linking asset_id=(?P<asset_id>\d+)"
    r" to record_id=(?P<record_id>[A-Za-z0-9-]+):\s*(?P<payload>\{.*)"
)


def extract_error_message(payload: str) -> str:
    """Pull error.message out of the JSON payload; fall back to raw text."""
    try:
        data = json.loads(payload.strip())
        return data["error"]["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return payload.strip()


def normalize(message: str) -> str:
    """Replace numbers so 'Asset 96828097 already linked' -> 'Asset <n> already linked'."""
    return re.sub(r"\d+", "<n>", message)


def main(file: str) -> None: # typescript tells me the output should be string and do 'Nothing' other than that. Meaning : No effect on the further function
    log_file = Path(HOME_REPO, log_path, file)
    print(log_file)
    if not log_file.is_file():
        sys.exit(f"Log file not found: {log_file}")

    records = []          # detailed rows for the CSV
    total_errors = 0      # every [ERROR] line, regardless of shape
    message_types = Counter()

    with log_file.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE_RE.match(line.strip())
            if not m or m.group("level") != "ERROR":
                continue

            total_errors += 1
            raw_message = m.group("message")

            link_m = LINK_ERROR_RE.search(raw_message)
            if link_m:
                err_msg = extract_error_message(link_m.group("payload"))
                records.append({
                    "timestamp": m.group("timestamp"),
                    "asset_id": link_m.group("asset_id"),
                    "record_id": link_m.group("record_id"),
                    "message": err_msg,
                    "raw_message": raw_message,
                })
                message_types[normalize(err_msg)] += 1
            else:
                # ERROR lines that don't match the link pattern still count
                message_types[normalize(raw_message)] += 1
                records.append({
                    "timestamp": m.group("timestamp"),
                    "asset_id": "",
                    "record_id": "",
                    "message": raw_message,
                    "raw_message": raw_message,
                })

    # 1) Detailed CSV
    match = re.search(r"^(?P<number>\d+_)", file)
    fund = match.group(1)
    print(fund)
    csv_path = Path(HOME_REPO, output_path, f"{fund}errors.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "asset_id", "record_id", "message", "raw_message"],
        )
        writer.writeheader()
        writer.writerows(records)

    # 2) Overview
    print(f"\n=== Error overview for {log_file.name} ===")
    print(f"Total errors = {total_errors}\n")
    for msg_type, count in message_types.most_common():
        pct = (count / total_errors * 100) if total_errors else 0
        print(f"{msg_type}: {count} ({pct:.1f}%)")

    print(f"\nDetailed CSV written to: {csv_path.resolve()}")

    #Write summary to txt file
    text_path = Path(HOME_REPO, output_path, f"{fund}summary.txt")
    txt_out = open(text_path, 'w')

    txt_out.write(f"\n=== Error overview for {log_file.name} ===\n")
    txt_out.write(f"Total errors = {total_errors}\n\n")
    for msg_type, count in message_types.most_common():
        pct = (count / total_errors * 100) if total_errors else 0
        txt_out.write(f"{msg_type}: {count} ({pct:.1f}%)\n")
    txt_out.write(f"\nDetailed CSV written to: {csv_path.resolve()}")

    txt_out.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python {Path(__file__).name} <logfile>")
    main(sys.argv[1])